import pytest

from mail_monitor.mailbox import Mailbox, MailboxError


async def test_list_inboxes_and_recent(fake_command):
    async with Mailbox(fake_command) as mailbox:
        tools = await mailbox.list_tools()
        assert {"listAccounts", "listFolders", "getRecentMessages", "getMessages", "updateMessage"} <= set(tools)

        inboxes = await mailbox.list_inboxes()
        assert [f.account_name for f in inboxes] == ["School", "Gmail"]
        assert all(f.type == "inbox" for f in inboxes)

        school = inboxes[0]
        headers = await mailbox.recent(school, days_back=2, max_results=100)
        subjects = {h.subject for h in headers}
        assert "Re: DoAtlas-2 progress numbers" in subjects
        assert "Course registration closes next week" not in subjects  # 100 小时前，超出 2 天
        prof = next(h for h in headers if h.sender_email == "prof@example.edu")
        assert prof.sender_name == "Prof. Example"
        assert prof.sender_domain == "example.edu"
        assert prof.account_name == "School"
        assert prof.date is not None and prof.date.tzinfo is not None


async def test_account_filter(fake_command):
    async with Mailbox(fake_command) as mailbox:
        inboxes = await mailbox.list_inboxes(["gmail"])
        assert [f.account_name for f in inboxes] == ["Gmail"]


async def test_fetch_bodies_and_add_tags(fake_command):
    async with Mailbox(fake_command) as mailbox:
        inboxes = await mailbox.list_inboxes()
        gmail = inboxes[1]
        headers = await mailbox.recent(gmail, days_back=2, max_results=100)
        refs = [(h.id, h.folder_path) for h in headers] + [("<missing@x>", gmail.path)]
        bodies = await mailbox.fetch_bodies(refs)
        hr = bodies["<hr-1@quantfirm.example>"]
        assert "first-round interview" in hr.body
        assert bodies["<missing@x>"].error == "Message not found"

        await mailbox.add_tags("<hr-1@quantfirm.example>", gmail.path, ["$label4"])
        updates = await mailbox.call("_fakeUpdates")
        assert updates[-1]["addTags"] == ["$label4"]


async def test_tool_error_becomes_mailbox_error(fake_command):
    async with Mailbox(fake_command) as mailbox:
        with pytest.raises(MailboxError, match="getMessages"):
            await mailbox.call("getMessages", messages=[])
