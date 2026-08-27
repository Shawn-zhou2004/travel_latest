from types import SimpleNamespace

from app.modules.media import cli
from app.modules.exports.service import EXPORT_EXPIRATION_CLEANUP_EVENT
from app.modules.media.service import MEDIA_UPLOAD_CLEANUP_EVENT


class FakeSession:
    def __init__(self, *, commit_error: Exception | None = None) -> None:
        self.commit_error = commit_error
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1
        if self.commit_error is not None:
            raise self.commit_error

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeSessionContext:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(self, *_args: object) -> None:
        return None


def test_enqueue_expired_upload_cleanup_commits_and_prints_event_identity(
    monkeypatch, capsys
) -> None:
    session = FakeSession()
    received_sessions: list[FakeSession] = []

    monkeypatch.setattr(cli, "Settings", lambda: SimpleNamespace(mysql_dsn="mysql+pymysql://configured"))
    monkeypatch.setattr(cli, "SessionLocal", lambda: FakeSessionContext(session))
    monkeypatch.setattr(
        cli,
        "enqueue_expired_upload_cleanup",
        lambda received_session: (
            received_sessions.append(received_session)
            or SimpleNamespace(event_id="event-123", event_type=MEDIA_UPLOAD_CLEANUP_EVENT)
        ),
    )

    assert cli.main(["enqueue-expired-upload-cleanup"]) == 0
    assert received_sessions == [session]
    assert session.commits == 1
    assert capsys.readouterr().out == f"event_id=event-123 event_type={MEDIA_UPLOAD_CLEANUP_EVENT}\n"


def test_enqueue_expired_upload_cleanup_reports_configuration_failure_without_details(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli, "Settings", lambda: (_ for _ in ()).throw(ValueError("MYSQL_DSN=password@host")))

    assert cli.main(["enqueue-expired-upload-cleanup"]) == 2
    captured = capsys.readouterr()
    assert "configuration invalid" in captured.err
    assert "password@host" not in captured.err


def test_enqueue_expired_upload_cleanup_rolls_back_and_hides_database_error(
    monkeypatch, capsys
) -> None:
    session = FakeSession(commit_error=RuntimeError("mysql://user:password@host"))

    monkeypatch.setattr(cli, "Settings", lambda: SimpleNamespace(mysql_dsn="mysql+pymysql://configured"))
    monkeypatch.setattr(cli, "SessionLocal", lambda: FakeSessionContext(session))
    monkeypatch.setattr(
        cli,
        "enqueue_expired_upload_cleanup",
        lambda _session: SimpleNamespace(event_id="event-123", event_type=MEDIA_UPLOAD_CLEANUP_EVENT),
    )

    assert cli.main(["enqueue-expired-upload-cleanup"]) == 2
    assert session.commits == 1
    assert session.rollbacks == 1
    captured = capsys.readouterr()
    assert "MySQL availability" in captured.err
    assert "password" not in captured.err


def test_enqueue_expired_cleanup_commits_both_events_atomically_and_prints_identities(
    monkeypatch, capsys
) -> None:
    session = FakeSession()
    received_sessions: list[FakeSession] = []

    monkeypatch.setattr(cli, "Settings", lambda: SimpleNamespace(mysql_dsn="mysql+pymysql://configured"))
    monkeypatch.setattr(cli, "SessionLocal", lambda: FakeSessionContext(session))
    monkeypatch.setattr(
        cli,
        "enqueue_expired_upload_cleanup",
        lambda received_session: (
            received_sessions.append(received_session)
            or SimpleNamespace(event_id="media-event-123", event_type=MEDIA_UPLOAD_CLEANUP_EVENT)
        ),
    )
    monkeypatch.setattr(
        cli,
        "enqueue_expired_export_cleanup",
        lambda received_session: (
            received_sessions.append(received_session)
            or SimpleNamespace(event_id="export-event-456", event_type=EXPORT_EXPIRATION_CLEANUP_EVENT)
        ),
    )

    assert cli.main(["enqueue-expired-cleanup"]) == 0
    assert received_sessions == [session, session]
    assert session.commits == 1
    assert session.rollbacks == 0
    assert capsys.readouterr().out == (
        f"event_id=media-event-123 event_type={MEDIA_UPLOAD_CLEANUP_EVENT}\n"
        f"event_id=export-event-456 event_type={EXPORT_EXPIRATION_CLEANUP_EVENT}\n"
    )


def test_enqueue_expired_cleanup_rolls_back_without_printing_when_second_enqueue_fails(
    monkeypatch, capsys
) -> None:
    session = FakeSession()

    monkeypatch.setattr(cli, "Settings", lambda: SimpleNamespace(mysql_dsn="mysql+pymysql://configured"))
    monkeypatch.setattr(cli, "SessionLocal", lambda: FakeSessionContext(session))
    monkeypatch.setattr(
        cli,
        "enqueue_expired_upload_cleanup",
        lambda _session: SimpleNamespace(event_id="media-event-123", event_type=MEDIA_UPLOAD_CLEANUP_EVENT),
    )
    monkeypatch.setattr(
        cli,
        "enqueue_expired_export_cleanup",
        lambda _session: (_ for _ in ()).throw(RuntimeError("mysql://user:password@host")),
    )

    assert cli.main(["enqueue-expired-cleanup"]) == 2
    assert session.commits == 0
    assert session.rollbacks == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "password" not in captured.err
