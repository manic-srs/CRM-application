"""AI drafting uses a mocked provider and an isolated database; never sends email."""
import json

import httpx
import pytest
from sqlalchemy import func, select

from app import ai_email, mailer
from app.database import get_db
from app.main import app
from app.models import Account, Email, Lead, Opportunity, RolePermission
from conftest import login_as


@pytest.fixture(autouse=True)
def isolate_key_configuration(monkeypatch):
    # Test requests must never read the real locally mounted key.
    monkeypatch.delenv("OPENAI_ENV_FILE", raising=False)


@pytest.fixture
def record(client, monkeypatch):
    monkeypatch.setattr(mailer, "send", lambda *a, **kw: None)
    response = client.post('/api/leads', json={"first_name": "Jack", "last_name": "Jones", "company": "Bluebird", "email": "jack@bluebird.example", "welcome_email": False})
    assert response.status_code == 201, response.text
    return response.json()


def request(record, **changes):
    return {"record_field": "lead_id", "record_id": record["id"], "instructions": "Thank Jack after the demo and ask about next steps.", **changes}


def model_reply(subject, body, outcome="draft"):
    return json.dumps({"outcome": outcome, "subject": subject, "body": body})


def completed(text=None):
    return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": text or model_reply("Next steps after our demo", "Hi Jack,\n\nThank you for your time. When would you like to discuss next steps?")}]}]}


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("EMAIL_DRAFT_MODE", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-a-real-key")
    captured = []
    reply = {"status": 200, "json": completed()}
    real_client = httpx.AsyncClient

    def handler(req):
        captured.append(req)
        if reply.get("error"):
            raise reply["error"]
        return httpx.Response(reply["status"], json=reply["json"])

    monkeypatch.setattr(ai_email.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    return captured, reply


def test_draft_uses_record_context_and_does_not_send_or_save(client, record, provider, monkeypatch):
    captured, _ = provider
    monkeypatch.setattr(mailer, "send", lambda *a, **kw: pytest.fail("Drafting must not send mail"))
    db = next(app.dependency_overrides[get_db]())
    before = db.scalar(select(func.count()).select_from(Email))
    response = client.post('/api/emails/draft', json=request(record))
    assert response.status_code == 200, response.text
    assert response.json()['subject'] == 'Next steps after our demo'
    assert response.json()['body'].endswith('Best regards,\nRavi Kumar\nravi@crm.test')
    payload = json.loads(captured[0].content)
    context = json.loads(payload['input'])
    assert context['crm_context']['first_name'] == 'Jack'
    assert context['crm_context']['current_stage'] == 'New'
    assert 'Introduce yourself' in context['stage_guidance']
    assert response.json()['stage'] == 'New'
    assert response.json()['mode'] == 'openai'
    assert 'jack@bluebird.example' not in payload['input']
    assert 'ravi@crm.test' not in payload['input']
    assert payload['store'] is False
    assert payload['text']['format']['strict'] is True
    assert db.scalar(select(func.count()).select_from(Email)) == before
    assert client.get(f"/api/leads/{record['id']}").json()['stage'] == 'New'
    db.close()


def test_missing_configuration_is_actionable(client, record, monkeypatch):
    monkeypatch.setenv('EMAIL_DRAFT_MODE', 'openai')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    assert client.get('/api/emails/settings').json()['ai_drafting_enabled'] is False
    response = client.post('/api/emails/draft', json=request(record))
    assert response.status_code == 503
    assert 'OPENAI_API_KEY' in response.json()['detail']


@pytest.mark.parametrize('action', ['formalize', 'friendly', 'shorten'])
def test_refinements_use_existing_draft_and_preserve_subject_and_stage(client, record, provider, monkeypatch, action):
    monkeypatch.setattr(mailer, 'send', lambda *a, **kw: pytest.fail('Refinement must not send email'))
    db = next(app.dependency_overrides[get_db]())
    db.get(Lead, record['id']).stage = 'Revisit'
    db.commit()
    original = 'Hi Jack,\n\nCould you confirm availability on November 12?\n\nBest regards,\nRavi Kumar\nravi@crm.test'
    provider[1]['json'] = completed(model_reply('Model changed subject', original))
    response = client.post('/api/emails/draft', json=request(
        record, action=action, instructions='', current_subject='Checking your availability', current_body=original))
    assert response.status_code == 200, response.text
    assert response.json()['subject'] == 'Checking your availability'
    assert response.json()['body'].count('Best regards,') == 1
    assert response.json()['record_stage'] == 'Revisit'
    payload = json.loads(json.loads(provider[0][0].content)['input'])
    assert payload['existing_message'] == original
    assert payload['email_action'] == action
    assert payload['user_request'] == ai_email.REFINEMENTS[action]
    assert payload['crm_context']['current_stage'] == 'Revisit'
    assert client.get(f"/api/leads/{record['id']}").json()['stage'] == 'Revisit'
    assert db.scalar(select(func.count()).select_from(Email)) == 0
    db.close()


@pytest.mark.parametrize('action', ['formalize', 'friendly', 'shorten'])
def test_refinements_require_existing_message_before_provider_call(client, record, provider, action):
    response = client.post('/api/emails/draft', json=request(record, action=action, current_body='   '))
    assert response.status_code == 422
    assert not provider[0]


@pytest.mark.parametrize('extra', [{'option_id': 'introduce'}, {'email_stage': 'Won'}])
def test_refinements_cannot_override_stage_or_select_a_template(client, record, provider, extra):
    response = client.post('/api/emails/draft', json=request(record, action='friendly', current_body='Hi Jack, let’s reconnect.', **extra))
    assert response.status_code == 422
    assert not provider[0]


def test_refinement_with_blank_subject_can_generate_a_subject(client, record, provider):
    response = client.post('/api/emails/draft', json=request(record, action='shorten', current_body='Hi Jack, please share your availability.'))
    assert response.status_code == 200
    assert response.json()['subject'] == 'Next steps after our demo'


def test_sample_mode_does_not_pretend_to_refine_existing_email(client, record, provider, monkeypatch):
    monkeypatch.setenv('EMAIL_DRAFT_MODE', 'sample')
    response = client.post('/api/emails/draft', json=request(record, action='formalize', current_body='Hi Jack, let’s reconnect.'))
    assert response.status_code == 422
    assert 'AI mode' in response.json()['detail']
    assert not provider[0]


def test_requires_login(client, record, provider):
    client.headers.pop('Authorization')
    assert client.post('/api/emails/draft', json=request(record)).status_code == 401
    assert not provider[0]


def test_cannot_draft_for_another_owners_record(client, record, provider):
    login_as(client, 1)
    other = client.post('/api/leads', json={"last_name": "Private", "company": "Private Inc", "welcome_email": False}).json()
    login_as(client, 2)
    assert client.post('/api/emails/draft', json=request(other)).status_code == 404
    assert not provider[0]


def test_requires_email_permission(client, record, provider):
    db = next(app.dependency_overrides[get_db]())
    db.add(RolePermission(role='Salesperson', permission='send_emails', allowed=False))
    db.commit()
    db.close()
    assert client.post('/api/emails/draft', json=request(record)).status_code == 403
    assert not provider[0]


@pytest.mark.parametrize('changes', [{"record_field": "users"}, {"record_id": 0}, {"stage": "Invalid"}, {"instructions": 'x' * 4001}, {"current_body": 'x' * 16001}, {"to": "extra@field.example"}])
def test_request_validation(client, record, provider, changes):
    assert client.post('/api/emails/draft', json=request(record, **changes)).status_code == 422
    assert not provider[0]


@pytest.mark.parametrize('status,expected', [(401, 502), (429, 429), (500, 502)])
def test_provider_errors_are_sanitized(client, record, provider, status, expected):
    _, reply = provider
    reply.update(status=status, json={"error": "SENSITIVE_PROVIDER_DETAIL"})
    response = client.post('/api/emails/draft', json=request(record))
    assert response.status_code == expected
    assert 'SENSITIVE_PROVIDER_DETAIL' not in response.text


@pytest.mark.parametrize('output', [completed('not JSON'), completed(model_reply('Hello', '')), completed(model_reply('Hello\nInjected', 'Text')), {"status": "incomplete", "output": []}])
def test_rejects_bad_or_incomplete_output(client, record, provider, output):
    provider[1]['json'] = output
    assert client.post('/api/emails/draft', json=request(record)).status_code == 502


def test_handles_refusal(client, record, provider):
    provider[1]['json'] = {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "Not available"}]}]}
    assert client.post('/api/emails/draft', json=request(record)).status_code == 422


def test_timeout_preserves_email(client, record, provider):
    provider[1]['error'] = httpx.ReadTimeout('timeout')
    response = client.post('/api/emails/draft', json=request(record))
    assert response.status_code == 504
    assert 'unchanged' in response.json()['detail']


def test_custom_model_and_current_message(client, record, provider, monkeypatch):
    monkeypatch.setenv('OPENAI_EMAIL_MODEL', 'configured-model')
    assert client.post('/api/emails/draft', json=request(record, current_subject='My subject', current_body='My draft')).status_code == 200
    payload = json.loads(provider[0][0].content)
    assert payload['model'] == 'configured-model'
    assert json.loads(payload['input'])['existing_message'] == 'My draft'


@pytest.mark.parametrize("stage", ["Unqualified", "New", "Nurturing", "Revisit", "Demo", "Converted", "Lost"])
def test_sample_mode_uses_real_lead_stage_without_a_provider(client, record, monkeypatch, stage):
    monkeypatch.setenv('EMAIL_DRAFT_MODE', 'sample')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setattr(ai_email.httpx, 'AsyncClient', lambda **kw: pytest.fail('Sample mode must not call OpenAI'))
    monkeypatch.setattr(mailer, 'send', lambda *a, **kw: pytest.fail('Drafts must not send mail'))
    db = next(app.dependency_overrides[get_db]())
    lead = db.get(Lead, record['id'])
    lead.stage = stage
    lead.lost_notes = 'INTERNAL_LOSS_NOTES'
    db.commit()
    before = db.scalar(select(func.count()).select_from(Email))
    response = client.post('/api/emails/draft', json=request(record))
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft['mode'] == 'sample'
    assert draft['stage'] == stage
    assert draft['subject'] == ai_email.SAMPLE_EMAILS[stage][0]
    assert draft['body'].startswith('Hi Jack,')
    assert 'INTERNAL_LOSS_NOTES' not in draft['body']
    assert draft['body'].endswith('Ravi Kumar\nravi@crm.test')
    assert db.scalar(select(func.count()).select_from(Email)) == before
    assert db.get(Lead, record['id']).stage == stage
    settings = client.get('/api/emails/settings').json()
    assert settings['draft_mode'] == 'sample'
    assert settings['ai_drafting_enabled'] is True
    db.close()


def test_client_cannot_override_the_real_stage(client, record, provider):
    assert client.post('/api/emails/draft', json=request(record, stage='Won')).status_code == 422
    assert not provider[0]


@pytest.mark.parametrize("action,subject", [("stage", "Let’s connect"), ("follow_up", "Following up on our conversation"), ("meeting", "A convenient time to connect"), ("thanks", "Thank you for your time")])
def test_four_sample_menu_actions_generate_relevant_emails(client, record, monkeypatch, action, subject):
    monkeypatch.setenv('EMAIL_DRAFT_MODE', 'sample')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setattr(ai_email.httpx, 'AsyncClient', lambda **kw: pytest.fail('Samples must not call OpenAI'))
    response = client.post('/api/emails/draft', json=request(record, action=action))
    assert response.status_code == 200, response.text
    assert response.json()['subject'] == subject
    assert response.json()['stage'] == 'New'
    assert response.json()['mode'] == 'sample'


def test_sample_mode_does_not_pretend_to_interpret_custom_requests(client, record, monkeypatch):
    monkeypatch.setenv('EMAIL_DRAFT_MODE', 'sample')
    response = client.post('/api/emails/draft', json=request(record, action='custom'))
    assert response.status_code == 422
    assert 'Custom descriptions need AI mode' in response.json()['detail']


def test_ai_menu_action_reaches_provider(client, record, provider):
    response = client.post('/api/emails/draft', json=request(record, action='meeting', instructions=''))
    assert response.status_code == 200
    content = json.loads(json.loads(provider[0][0].content)['input'])
    assert content['email_action'] == 'meeting'
    assert 'arrange a meeting' in content['user_request']
    assert content['crm_context']['current_stage'] == 'New'


def test_key_is_read_from_secret_file_without_exporting_it(tmp_path, monkeypatch):
    config = tmp_path / '.env'
    config.write_text('OPENAI_API_KEY="synthetic-local-test-key"\n')
    monkeypatch.setenv('OPENAI_ENV_FILE', str(config))
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    assert ai_email.api_key() == 'synthetic-local-test-key'
    import os
    assert 'OPENAI_API_KEY' not in os.environ


def test_missing_secret_file_does_not_use_an_unintended_environment_key(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENAI_ENV_FILE', str(tmp_path / 'absent.env'))
    monkeypatch.setenv('OPENAI_API_KEY', 'do-not-use-this-key')
    assert ai_email.api_key() == ''


@pytest.mark.parametrize('code,expected', [('credit_balance_exhausted','no API credits'), ('insufficient_quota','no available API quota'), ('billing_hard_limit_reached','API billing limit'), ('organization_spend_limit_exceeded','organization reached'), ('project_spend_limit_exceeded','project reached'), ('organization_usage_limit_exceeded','API usage limit')])
def test_quota_errors_have_actionable_sanitized_messages(client, record, provider, code, expected):
    provider[1].update(status=429, json={'error': {'code':code, 'message':'PRIVATE_PROVIDER_DETAIL'}})
    response=client.post('/api/emails/draft',json=request(record))
    assert response.status_code == 429
    assert expected in response.json()['detail']
    assert 'PRIVATE_PROVIDER_DETAIL' not in response.text


@pytest.mark.parametrize('stage,labels', [
    ('New', ['Introduce yourself and your company', 'Understand their needs and priorities', 'Share information relevant to their needs', 'Offer a brief discovery conversation']),
    ('Nurturing', ['Follow up on their current priorities', 'Share information relevant to their needs', 'Ask what questions they need answered', 'Offer a conversation when they’re ready']),
    ('Demo', ['Offer a demo focused on their needs', 'Confirm the demo agenda and availability', 'Request feedback after a completed demo', 'Ask which topics the demo should cover']),
    ('Converted', ['Thank them for continuing the discussion', 'Introduce the account team', 'Align on priorities and next steps', 'Offer a conversation when they’re ready']),
    ('Lost', ['Thank them for their time', 'Invite optional feedback on their decision', 'Offer to reconnect if their needs change', 'Close the conversation respectfully']),
])
def test_lead_menus_and_all_four_drafts_follow_database_stage(client, record, monkeypatch, stage, labels):
    monkeypatch.setenv('EMAIL_DRAFT_MODE', 'sample')
    monkeypatch.setattr(ai_email.httpx, 'AsyncClient', lambda **kw: pytest.fail('Menu and samples must not call OpenAI'))
    db = next(app.dependency_overrides[get_db]())
    db.get(Lead, record['id']).stage = stage
    db.commit()
    url=f"/api/emails/draft-options?record_field=lead_id&record_id={record['id']}"
    response=client.get(url)
    assert response.status_code == 200
    menu=response.json()
    assert menu['stage'] == stage
    assert [option['label'] for option in menu['options']] == labels
    assert len({option['option_id'] for option in menu['options']}) == 4
    drafts=[]
    for option in menu['options']:
        response=client.post('/api/emails/draft',json=request(record, option_id=option['option_id'], instructions=''))
        assert response.status_code == 200, response.text
        draft=response.json()
        assert draft['stage'] == stage
        assert draft['body'].startswith('Hi Jack,')
        drafts.append(draft['subject'])
    assert len(set(drafts)) == 4
    db.close()


def test_old_stage_options_are_rejected_without_a_model_call(client, record, provider):
    response=client.post('/api/emails/draft',json=request(record,option_id='invite_demo'))
    assert response.status_code == 409
    assert 'current stage' in response.json()['detail']
    assert not provider[0]


def test_menu_refreshes_after_a_stage_change(client, record):
    url=f"/api/emails/draft-options?record_field=lead_id&record_id={record['id']}"
    before=client.get(url).json()
    db=next(app.dependency_overrides[get_db]())
    db.get(Lead,record['id']).stage='Demo'
    db.commit()
    after=client.get(url).json()
    assert before['stage']=='New'
    assert after['stage']=='Demo'
    assert before['options'] != after['options']
    db.close()


def test_stage_specific_choice_reaches_the_real_provider_adapter(client, record, provider):
    response=client.post('/api/emails/draft',json=request(record,option_id='discover_needs',instructions=''))
    assert response.status_code == 200
    payload=json.loads(json.loads(provider[0][0].content)['input'])
    assert payload['email_action']=='discover_needs'
    assert 'goals, and priorities' in payload['user_request']
    assert payload['crm_context']['current_stage']=='New'


def test_draft_menu_requires_record_access_and_email_permission(client, record):
    url=f"/api/emails/draft-options?record_field=lead_id&record_id={record['id']}"
    login_as(client,1)
    other=client.post('/api/leads',json={'last_name':'Other','company':'Private','welcome_email':False}).json()
    login_as(client,2)
    assert client.get(f"/api/emails/draft-options?record_field=lead_id&record_id={other['id']}").status_code == 404
    db=next(app.dependency_overrides[get_db]())
    db.add(RolePermission(role='Salesperson',permission='send_emails',allowed=False))
    db.commit()
    assert client.get(url).status_code == 403
    client.headers.pop('Authorization')
    assert client.get(url).status_code == 401
    db.close()


@pytest.mark.parametrize('stage', ['Unqualified','New','Nurturing','Revisit','Demo','Converted','Lost'])
def test_free_text_drafts_receive_actual_stage_and_preserve_user_intent(client, record, provider, stage):
    db=next(app.dependency_overrides[get_db]())
    db.get(Lead,record['id']).stage=stage
    db.commit()
    text='Ask about their priorities and offer a short conversation. Keep it under 100 words.'
    response=client.post('/api/emails/draft',json=request(record,action='custom',instructions=text))
    assert response.status_code == 200
    sent=json.loads(provider[0][0].content)
    payload=json.loads(sent['input'])
    assert payload['user_request'] == text
    assert payload['crm_context']['current_stage'] == stage
    assert payload['stage_guidance'] == ai_email.STAGE_GUIDANCE[stage]
    assert payload['email_action'] == 'custom'
    assert response.json()['body'].count('Best regards,') == 1
    db.close()


@pytest.mark.parametrize('stage', ['New', 'Nurturing', 'Demo', 'Converted', 'Lost'])
def test_inline_suggestion_can_be_edited_before_generation(client, record, provider, stage):
    db = next(app.dependency_overrides[get_db]())
    db.get(Lead, record['id']).stage = stage
    db.commit()
    menu = client.get('/api/emails/draft-options', params={
        'record_field': 'lead_id', 'record_id': record['id'],
    }).json()
    assert menu['stage'] == stage
    assert len(menu['options']) == 4
    description = menu['options'][0]['prompt'] + ' Focus on reporting needs; keep it under 70 words.'
    response = client.post('/api/emails/draft', json=request(record, action='custom', instructions=description))
    assert response.status_code == 200
    payload = json.loads(json.loads(provider[0][0].content)['input'])
    assert payload['user_request'] == description
    assert payload['email_stage'] == stage
    assert client.get(f"/api/leads/{record['id']}").json()['stage'] == stage
    db.close()


def test_generation_rechecks_stage_after_suggestions_were_loaded(client, record, provider):
    menu = client.get('/api/emails/draft-options', params={
        'record_field': 'lead_id', 'record_id': record['id'],
    }).json()
    db = next(app.dependency_overrides[get_db]())
    db.get(Lead, record['id']).stage = 'Nurturing'
    db.commit()
    response = client.post('/api/emails/draft', json=request(
        record, action='custom', instructions=menu['options'][0]['prompt']))
    assert response.status_code == 200
    assert response.json()['record_stage'] == 'Nurturing'
    payload = json.loads(json.loads(provider[0][0].content)['input'])
    assert payload['stage_guidance'] == ai_email.STAGE_GUIDANCE['Nurturing']
    db.close()


@pytest.mark.parametrize('stage', ['Opportunity', 'Proposal', 'Won', 'Lost'])
def test_opportunity_suggestions_and_drafts_follow_opportunity_stage(client, provider, stage):
    db = next(app.dependency_overrides[get_db]())
    account = Account(name='Example customer', owner_id=2)
    db.add(account)
    db.flush()
    opportunity = Opportunity(name='Reporting project', account_id=account.id, owner_id=2, stage=stage)
    db.add(opportunity)
    db.commit()
    menu = client.get('/api/emails/draft-options', params={
        'record_field': 'opportunity_id', 'record_id': opportunity.id,
    }).json()
    assert menu['stage'] == stage
    assert len(menu['options']) == 4
    description = menu['options'][0]['prompt'] + ' Keep the tone friendly.'
    response = client.post('/api/emails/draft', json={
        'record_field': 'opportunity_id', 'record_id': opportunity.id,
        'action': 'custom', 'instructions': description,
    })
    assert response.status_code == 200, response.text
    payload = json.loads(json.loads(provider[0][0].content)['input'])
    assert payload['crm_context']['record_type'] == 'Opportunity'
    assert payload['crm_context']['current_stage'] == stage
    assert payload['stage_guidance'] == ai_email.STAGE_GUIDANCE[stage]
    assert payload['user_request'] == description
    db.refresh(opportunity)
    assert opportunity.stage == stage
    db.close()


@pytest.mark.parametrize('closing', [
    'Best regards,',
    'Best regards,\nRavi Kumar\nravi@crm.test',
    'Best regards,\n[Your Name]\n[Your Title]\n[Your Company]',
    'Kind regards,\n[Your Name]',
    'Best regards, Ravi Kumar',
    'BEST REGARDS,\nRavi Kumar',
    '**Best regards**,\n[Your Name]',
    'Best regards,\nRavi Kumar\nravi@crm.test\n\nBest regards,\nRavi Kumar\nravi@crm.test',
])
def test_model_signature_is_not_added_twice(client, record, provider, closing):
    body='Hi Jack,\n\nWould a short conversation about your priorities be helpful?'
    provider[1]['json']=completed(model_reply('Discussing your priorities', body+'\n\n'+closing))
    response=client.post('/api/emails/draft',json=request(record,action='custom'))
    assert response.status_code == 200, response.text
    expected=body+'\n\nBest regards,\nRavi Kumar\nravi@crm.test'
    assert response.json()['body'] == expected
    assert response.json()['body'].count('Best regards,') == 1


def test_signature_normalization_is_idempotent():
    once=ai_email.with_sender_signature('Hi Jack,\n\nPlease let me know your availability.', 'Ravi Kumar', 'ravi@crm.test')
    assert ai_email.with_sender_signature(once,'Ravi Kumar','ravi@crm.test') == once


def test_signature_normalization_preserves_body_text_that_mentions_a_closing():
    body='Hi Jack,\n\nPlease use the closing phrase below in the document:\nBest regards\nis the phrase our team uses.\n\nThank you for your help.'
    assert ai_email.with_sender_signature(body,'Ravi Kumar','ravi@crm.test').startswith(body+'\n\n')


@pytest.mark.parametrize('email_stage', ['Unqualified','New','Nurturing','Revisit','Demo','Converted','Opportunity','Discovery','Proposal','Won','Lost'])
def test_email_stage_selection_changes_draft_context_not_crm_record(client, record, provider, monkeypatch, email_stage):
    monkeypatch.setattr(mailer,'send',lambda *a,**kw: pytest.fail('Drafting must not send email'))
    response=client.post('/api/emails/draft',json=request(record,action='custom',email_stage=email_stage))
    assert response.status_code == 200, response.text
    assert response.json()['stage'] == email_stage
    assert response.json()['record_stage'] == 'New'
    content=json.loads(json.loads(provider[0][0].content)['input'])
    assert content['email_stage'] == email_stage
    assert content['stage_guidance'] == ai_email.STAGE_GUIDANCE[email_stage]
    assert content['crm_context']['current_stage'] == 'New'
    assert client.get(f"/api/leads/{record['id']}").json()['stage'] == 'New'


def test_invalid_email_stage_is_rejected_before_model_call(client, record, provider):
    response=client.post('/api/emails/draft',json=request(record,email_stage='Invalid'))
    assert response.status_code == 422
    assert not provider[0]


def test_stage_alone_can_generate_a_draft(client, record, provider):
    response=client.post('/api/emails/draft',json=request(record,action='custom',email_stage='Nurturing',instructions=''))
    assert response.status_code == 200
    content=json.loads(json.loads(provider[0][0].content)['input'])
    assert content['email_stage']=='Nurturing'
    assert content['stage_guidance']==ai_email.STAGE_GUIDANCE['Nurturing']


def test_default_email_stage_tracks_current_record(client, record, provider):
    db=next(app.dependency_overrides[get_db]())
    db.get(Lead,record['id']).stage='Demo'
    db.commit()
    response=client.post('/api/emails/draft',json=request(record,email_stage=None,action='custom'))
    assert response.status_code == 200
    assert response.json()['stage']=='Demo'
    assert response.json()['record_stage']=='Demo'
    content=json.loads(json.loads(provider[0][0].content)['input'])
    assert content['email_stage']=='Demo'
    db.close()


# ---------- the drafting bar: new email or revision, CRM-only scope (all replies are mocked) ----------

STARTER = 'Hi Jack,\n\n\n\nBest regards,\nRavi Kumar\nravi@crm.test'  # what New Email starts with for Ravi
DRAFT = ('Hi Jack,\n\nThank you for the demo on November 12. The proposal covers 25 seats at $40 per seat.\n\n'
         'Best regards,\nRavi Kumar\nravi@crm.test')
UNRELATED = ['Write a leave request to my manager for next Friday.', 'Apply for vacation from December 20 to January 2.',
             'Ask for a day off tomorrow.', 'Write a poem about autumn.', 'Draft my resignation letter.']


def sent_input(provider):
    return json.loads(json.loads(provider[0][0].content)['input'])


@pytest.mark.parametrize('body,content', [
    (STARTER, ''), ('', ''), ('Hello,', ''), ('Good morning Jack,\n\nBest regards,', ''),
    ('  Dear Jack Jones,  \n\n Kind regards,\nRavi Kumar\nravi@crm.test', ''),
    ('Hi Jack, let’s reconnect.', 'Hi Jack, let’s reconnect.'),
    ('Hi Jack,\n\nThanks for your time.\n\nBest regards,\nRavi Kumar', 'Thanks for your time.'),
    ('Could you share your availability?', 'Could you share your availability?'),
])
def test_draft_content_ignores_only_the_greeting_and_signature(body, content):
    assert ai_email.draft_content(body, 'Ravi Kumar', 'ravi@crm.test') == content


@pytest.mark.parametrize('body', ['', STARTER, 'Hello,\n\nBest regards,\nRavi Kumar'])
def test_a_greeting_and_signature_alone_asks_for_a_new_email(client, record, provider, body):
    response = client.post('/api/emails/draft', json=request(
        record, action='custom', instructions='Invite Jack to a product demo.', current_body=body))
    assert response.status_code == 200, response.text
    draft = response.json()
    assert (draft['subject'], draft['draft_type']) == ('Next steps after our demo', 'new')
    assert draft['body'].startswith('Hi Jack,') and draft['body'].count('Best regards,') == 1
    sent = sent_input(provider)
    assert (sent['task'], sent['existing_message']) == ('new_email', '')


def test_a_new_draft_keeps_the_users_subject_and_fills_a_blank_one(client, record, provider):
    ask = request(record, action='custom', instructions='Invite Jack to a product demo.', current_body=STARTER)
    kept = client.post('/api/emails/draft', json={**ask, 'current_subject': 'Demo invitation'}).json()
    assert (kept['subject'], kept['draft_type']) == ('Demo invitation', 'new')
    assert client.post('/api/emails/draft', json=ask).json()['subject'] == 'Next steps after our demo'


def test_the_subject_changes_only_when_the_request_asks_for_it(client, record, provider):
    response = client.post('/api/emails/draft', json=request(
        record, action='custom', instructions='Invite Jack to a demo and suggest a clearer subject.',
        current_subject='Hello', current_body=STARTER))
    assert response.json()['subject'] == 'Next steps after our demo'


def test_a_request_on_an_existing_draft_revises_it_and_keeps_the_subject(client, record, provider):
    provider[1]['json'] = completed(model_reply('A subject from the model', DRAFT.replace('Thank you', 'Many thanks')))
    response = client.post('/api/emails/draft', json=request(
        record, action='custom', instructions='Make the opening warmer.', current_subject='Your proposal', current_body=DRAFT))
    assert response.status_code == 200, response.text
    draft = response.json()
    assert (draft['subject'], draft['draft_type']) == ('Your proposal', 'revision')
    assert draft['body'].count('Best regards,') == 1 and draft['body'].startswith('Hi Jack,\n\nMany thanks')
    sent = sent_input(provider)
    assert (sent['task'], sent['existing_message'], sent['user_request']) == ('revise_email', DRAFT, 'Make the opening warmer.')


@pytest.mark.parametrize('action', ['formalize', 'friendly', 'shorten'])
@pytest.mark.parametrize('body', [STARTER, 'Hello,\n\nKind regards,\nRavi Kumar'])
def test_refine_needs_more_than_a_greeting_and_signature(client, record, provider, action, body):
    response = client.post('/api/emails/draft', json=request(record, action=action, instructions='', current_body=body))
    assert response.status_code == 422 and response.json()['detail'] == ai_email.DESCRIBE_FIRST
    assert not provider[0]


@pytest.mark.parametrize('action,label', [('formalize', 'Professional'), ('friendly', 'Conversational'), ('shorten', 'Concise')])
def test_refine_keeps_the_facts_the_subject_and_one_signature(client, record, provider, action, label):
    # the mocked model keeps the facts and repeats the signature; the server keeps one signature and the subject
    provider[1]['json'] = completed(model_reply('A subject from the model', DRAFT + '\n\nBest regards,\nRavi Kumar'))
    response = client.post('/api/emails/draft', json=request(
        record, action=action, instructions='', current_subject='Your proposal', current_body=DRAFT))
    assert response.status_code == 200, response.text
    draft = response.json()
    assert (draft['subject'], draft['draft_type']) == ('Your proposal', 'revision')
    assert draft['body'].count('Best regards,') == 1 and draft['body'].count('ravi@crm.test') == 1
    assert all(fact in draft['body'] for fact in ('November 12', '25 seats', '$40'))
    sent = sent_input(provider)
    assert sent['task'] == 'revise_email' and sent['user_request'].startswith(label + ':')


@pytest.mark.parametrize('instructions', UNRELATED)
@pytest.mark.parametrize('extra', [{'action': 'custom'}, {'action': 'stage'}, {'action': 'meeting'},
                                   {'action': 'custom', 'email_stage': 'Won'}, {'option_id': 'introduce'}])
def test_clearly_unrelated_requests_are_refused_before_any_call_whatever_the_action_or_stage(client, record, provider, instructions, extra):
    response = client.post('/api/emails/draft', json=request(
        record, instructions=instructions, current_subject='Kept', current_body=DRAFT, **extra))
    assert response.status_code == 422 and response.json()['detail'] == ai_email.OUT_OF_SCOPE
    assert not provider[0]


def test_a_customer_note_that_mentions_leave_is_left_to_the_model(client, record, provider):
    response = client.post('/api/emails/draft', json=request(
        record, action='custom', instructions="Tell Jack I'm on annual leave next week and Priya will look after his account."))
    assert response.status_code == 200 and len(provider[0]) == 1


@pytest.mark.parametrize('extra', [{'action': 'custom'}, {'action': 'stage'}, {'action': 'thanks'},
                                   {'action': 'custom', 'email_stage': 'Proposal'}, {'option_id': 'discover_needs'},
                                   {'action': 'formalize', 'instructions': ''}])
def test_the_models_unsupported_outcome_holds_for_every_action_and_stage(client, record, provider, extra):
    provider[1]['json'] = completed(model_reply('Heater repair', 'Dear landlord, the heater is broken.', outcome='unsupported'))
    response = client.post('/api/emails/draft', json={**request(
        record, instructions='Write to my landlord about the broken heater.', current_subject='Kept', current_body=DRAFT), **extra})
    assert response.status_code == 422 and response.json()['detail'] == ai_email.OUT_OF_SCOPE
    assert 'landlord' not in response.text and len(provider[0]) == 1  # the model's text is never returned


def test_a_vague_request_asks_for_sales_context(client, record, provider):
    provider[1]['json'] = completed(model_reply('', '', outcome='needs_context'))
    response = client.post('/api/emails/draft', json=request(record, action='custom', instructions='Write something.', current_body=STARTER))
    assert response.status_code == 422 and response.json()['detail'] == ai_email.NEEDS_CONTEXT


@pytest.mark.parametrize('output', [
    completed(json.dumps({'subject': 'Hello', 'body': 'Hi Jack,\n\nText'})),                     # no outcome
    completed(model_reply('Hello', 'Hi Jack,\n\nText', outcome='maybe')),                       # unknown outcome
    completed(json.dumps({'outcome': 'draft', 'subject': 'Hi', 'body': 'Text', 'to': 'x@example.test'})),  # extra field
    completed(model_reply('', 'Hi Jack,\n\nText')),                                             # no subject to fill one
    completed(model_reply('Hello', 'Hi Jack,\n\nBest regards,\nRavi Kumar\nravi@crm.test')),     # greeting and signature
    completed(model_reply('Hello', '   ')),                                                     # empty body
    {'status': 'completed', 'output': []},                                                      # nothing at all
])
def test_unusable_model_output_is_rejected_so_nothing_is_applied(client, record, provider, output):
    provider[1]['json'] = output
    response = client.post('/api/emails/draft', json=request(record, action='custom', current_body=STARTER))
    assert response.status_code == 502 and 'unchanged' in response.json()['detail']


def test_links_the_user_did_not_supply_are_replaced(client, record, provider):
    provider[1]['json'] = completed(model_reply('Demo', 'Hi Jack,\n\nBook a slot at https://booking.example/ravi or see '
                                                       'www.vendor.example/pricing. Our guide: https://docs.example.test/start.'))
    response = client.post('/api/emails/draft', json=request(
        record, action='custom', instructions='Invite Jack to a demo and link our guide https://docs.example.test/start'))
    body = response.json()['body']
    assert 'booking.example' not in body and 'vendor.example' not in body and body.count('[link]') == 2
    assert 'Our guide: https://docs.example.test/start.' in body


def test_another_recipient_is_not_greeted_by_the_records_name(client, record, provider):
    client.post('/api/emails/draft', json=request(record, action='custom', recipient_is_record_contact=False))
    context = sent_input(provider)['crm_context']
    assert 'first_name' not in context and 'last_name' not in context
    assert context['recipient_is_record_contact'] is False and context['company'] == 'Bluebird'


def test_a_draft_returns_only_the_email_text_and_changes_nothing_on_the_record(client, record, provider):
    fields = ('stage', 'owner_id', 'email', 'company')
    before = client.get(f"/api/leads/{record['id']}").json()
    response = client.post('/api/emails/draft', json=request(record, action='custom', current_body=STARTER))
    assert set(response.json()) == {'subject', 'body', 'draft_type', 'stage', 'record_stage', 'mode'}
    after = client.get(f"/api/leads/{record['id']}").json()
    assert {f: after[f] for f in fields} == {f: before[f] for f in fields}


def test_instructions_state_the_scope_recipient_and_untrusted_text():
    for phrase in ('"unsupported"', '"needs_context"', 'manager', 'untrusted data', 'meeting links'):
        assert phrase in ai_email.INSTRUCTIONS
