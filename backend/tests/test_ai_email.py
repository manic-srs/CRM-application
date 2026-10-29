"""AI drafting uses a mocked provider and an isolated database; never sends email."""
import json

import httpx
import pytest
from sqlalchemy import func, select

from app import ai_email, mailer
from app.database import get_db
from app.main import app
from app.models import Email, Lead, RolePermission
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


def completed(text=None):
    return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": text or json.dumps({"subject": "Next steps after our demo", "body": "Hi Jack,\n\nThank you for your time. When would you like to discuss next steps?"})}]}]}


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


@pytest.mark.parametrize('output', [completed('not JSON'), completed('{"subject":"Hello","body":""}'), completed('{"subject":"Hello\\nInjected","body":"Text"}'), {"status": "incomplete", "output": []}])
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


@pytest.mark.parametrize("stage", ["New", "Nurturing", "Demo", "Converted", "Lost"])
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
    ('New', ['Introduce our company', 'Ask about their requirements', 'Offer helpful information', 'Schedule an introductory call']),
    ('Nurturing', ['Check in on their interest', 'Offer helpful information', 'Offer to answer questions', 'Arrange a follow-up conversation']),
    ('Demo', ['Invite them to a demo', 'Confirm demo arrangements', 'Follow up on the demo', 'Ask for demo questions']),
    ('Converted', ['Thank them for moving forward', 'Introduce the account team', 'Confirm the next steps', 'Arrange a follow-up conversation']),
    ('Lost', ['Thank them for their time', 'Ask for feedback', 'Leave the door open', 'Send a polite closing email']),
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
