"""Customer-facing email choices, selected from the record's current sales stage."""
from dataclasses import dataclass


@dataclass(frozen=True)
class EmailOption:
    label: str
    instruction: str
    subject: str
    sample: str


OPTIONS = {
    "introduce": EmailOption("Introduce our company", "Introduce the sender and company without inventing products or company facts. Offer to learn about the customer's needs.", "A quick introduction", "I wanted to introduce myself and learn more about your business. I would be happy to discuss your priorities and explore how our team might help."),
    "discover_needs": EmailOption("Ask about their requirements", "Ask about the customer's needs, goals, and priorities. Avoid assumptions about their requirements.", "Understanding your requirements", "I would love to learn more about your requirements and priorities. What goals or challenges would you like our team to focus on?"),
    "share_information": EmailOption("Offer helpful information", "Offer relevant information and ask which topics are most useful. Do not invent product features or claim attachments are included.", "How can we help?", "I would be happy to share more information based on your interests. Please let me know which topics or questions would be most helpful for your team."),
    "schedule_call": EmailOption("Schedule an introductory call", "Ask for availability for a short introductory call. Do not invent a scheduled date.", "A convenient time to connect", "Would you be available for a short introductory call? Please share a convenient time, and I will be happy to coordinate."),
    "check_interest": EmailOption("Check in on their interest", "Gently check whether the customer is still interested. Ask about priorities without pressure.", "Checking in on your priorities", "I wanted to check in and see whether you would like to continue our conversation. Please let me know if your priorities have changed or if there is anything we can help with."),
    "answer_questions": EmailOption("Offer to answer questions", "Offer to answer the customer's questions without inventing their concerns or answers.", "Any questions we can help with?", "I wanted to see if you have any questions we can help with. Please let me know what you would like to explore in more detail."),
    "schedule_follow_up": EmailOption("Arrange a follow-up conversation", "Ask for availability for a follow-up discussion appropriate to the current stage.", "A time to discuss next steps", "Would it be helpful to arrange a follow-up conversation? Please share your availability and any topics you would like to discuss."),
    "invite_demo": EmailOption("Invite them to a demo", "Invite the customer to a demonstration. Ask for availability and topics; do not invent product features or a date.", "An invitation to a demo", "We would be happy to arrange a demonstration focused on your needs. Please share your availability and the areas you would like us to cover."),
    "confirm_demo": EmailOption("Confirm demo arrangements", "Ask the customer to confirm demo arrangements. Use [demo date and time] if no confirmed details are supplied; do not claim the demo occurred.", "Confirming your demo arrangements", "Could you please confirm whether [demo date and time] works for your team? Please also let us know who will be joining and any topics you would like to cover."),
    "demo_follow_up": EmailOption("Follow up on the demo", "Draft a post-demo follow-up thanking the customer for their time and asking for feedback. Do not invent demo details or attendance facts beyond the chosen post-demo purpose.", "Following up on the demo", "Thank you for taking the time to explore the demo with us. We would welcome your feedback and any questions you would like to discuss next."),
    "demo_questions": EmailOption("Ask for demo questions", "Ask which questions or topics the customer wants covered around the demo. Do not assume it has already happened.", "Questions for your demo", "Are there any questions or topics you would like us to address around your demo? We would be happy to focus the conversation on what matters most to your team."),
    "thank_interest": EmailOption("Thank them for moving forward", "Thank the customer for continuing the sales conversation after lead conversion. Do not imply a contract or won deal.", "Thank you for continuing the conversation", "Thank you for continuing the conversation with us. We appreciate the opportunity to explore your needs and work through the next steps together."),
    "introduce_team": EmailOption("Introduce the account team", "Draft an account team introduction using [team member name] and [role] placeholders. Do not invent people or imply a won deal.", "Introducing your account team", "I would like to introduce [team member name], our [role], who can help with your next steps. Please let us know how we can best support your ongoing discussions."),
    "confirm_next_steps": EmailOption("Confirm the next steps", "Ask to align on the next sales steps after conversion or during an opportunity. Do not imply a deal has been won.", "Aligning on next steps", "I would like to align on the next steps in our conversation. Could you share your priorities and any questions we should address before moving forward?"),
    "thank_time": EmailOption("Thank them for their time", "Thank the customer politely for considering us. Do not reveal any internal lost reason or pressure them to reconsider.", "Thank you for your time", "Thank you for your time and for considering our team. We appreciate the opportunity to learn about your needs and wish you and your team continued success."),
    "request_feedback": EmailOption("Ask for feedback", "Ask for optional feedback on the customer's experience. Do not reveal internal lost reasons or assume why they declined.", "We would value your feedback", "Thank you again for considering us. If you are comfortable sharing, we would value any feedback on your experience and how we could improve. There is no obligation to respond."),
    "stay_in_touch": EmailOption("Leave the door open", "Offer to reconnect if priorities change, with no pressure and no claims about why the deal was lost.", "Happy to reconnect in the future", "We appreciate the opportunity to speak with your team. If your needs or priorities change in the future, we would be happy to reconnect. Please feel free to reach out whenever it is useful."),
    "close_conversation": EmailOption("Send a polite closing email", "Close the sales conversation politely with no further action required. Do not disclose internal loss notes or pressure the customer.", "Thank you and best wishes", "Thank you for considering us. We will close out this conversation for now, and no further action is needed from you. Wishing you and your team all the best."),
    "discuss_solution": EmailOption("Discuss a possible solution", "Ask to discuss possible approaches based on the customer's requirements. Do not invent capabilities, pricing, or guarantees.", "Exploring a possible approach", "We would welcome the opportunity to discuss an approach that fits your priorities. Could you share the requirements and outcomes that matter most to your team?"),
    "proposal_overview": EmailOption("Introduce the proposal", "Draft a proposal introduction with [proposal details] placeholders. Do not claim a file is attached or invent pricing.", "A proposal for your consideration", "I would like to share a proposal for your consideration: [proposal details]. Please let me know if you would like to discuss the scope or have any questions."),
    "proposal_follow_up": EmailOption("Follow up on the proposal", "Follow up on the proposal and ask whether the customer would like to discuss it. Do not invent delivery or review dates.", "Following up on the proposal", "I wanted to follow up on our proposal and see if you have any questions. Please let me know if a conversation about the scope or next steps would be helpful."),
    "proposal_questions": EmailOption("Ask about proposal questions", "Invite questions about the proposal without inventing terms, discounts, or objections.", "Questions about the proposal", "Are there any aspects of the proposal you would like us to clarify? We would be happy to discuss your questions and make sure the next steps are clear."),
    "proposal_review": EmailOption("Arrange a proposal review", "Ask for availability to review the proposal together. Do not invent scheduled dates or agreed terms.", "A time to review the proposal", "Would you be available to review the proposal together? Please share a convenient time and any questions you would like us to address."),
    "thank_business": EmailOption("Thank them for choosing us", "Thank the customer for choosing us after the deal is won. Do not invent contract values or delivery commitments.", "Thank you for choosing us", "Thank you for choosing to work with us. We appreciate your trust and look forward to supporting your team."),
    "welcome_customer": EmailOption("Welcome the new customer", "Welcome the customer warmly after a won deal without inventing onboarding dates or account details.", "Welcome aboard", "We are delighted to welcome you as a customer. Our team looks forward to working with you and helping coordinate a smooth start."),
    "onboarding_steps": EmailOption("Discuss onboarding next steps", "Offer to coordinate onboarding after a won deal. Ask about priorities; use placeholders for unspecified requirements or timelines.", "Your onboarding next steps", "We would be happy to coordinate the next steps for onboarding. Please let us know your priorities and the best person to work with on your team."),
    "schedule_kickoff": EmailOption("Schedule a kickoff meeting", "Ask for availability for a customer kickoff after a won deal. Do not invent a scheduled date or attendees.", "Arranging your kickoff meeting", "We would like to arrange a kickoff meeting with your team. Please share your availability and who you would like to include, and we will coordinate the details."),
}

STAGE_OPTIONS = {
    "New": ("introduce", "discover_needs", "share_information", "schedule_call"),
    "Nurturing": ("check_interest", "share_information", "answer_questions", "schedule_follow_up"),
    "Demo": ("invite_demo", "confirm_demo", "demo_follow_up", "demo_questions"),
    "Converted": ("thank_interest", "introduce_team", "confirm_next_steps", "schedule_follow_up"),
    "Lost": ("thank_time", "request_feedback", "stay_in_touch", "close_conversation"),
    "Opportunity": ("discover_needs", "discuss_solution", "confirm_next_steps", "schedule_call"),
    "Proposal": ("proposal_overview", "proposal_follow_up", "proposal_questions", "proposal_review"),
    "Won": ("thank_business", "welcome_customer", "onboarding_steps", "schedule_kickoff"),
}
GENERAL_OPTIONS = ("introduce", "schedule_follow_up", "schedule_call", "thank_time")


def option_ids(stage):
    return STAGE_OPTIONS.get(stage, GENERAL_OPTIONS)


def menu(stage):
    return {"stage": stage, "options": [{"option_id": key, "label": OPTIONS[key].label} for key in option_ids(stage)]}
