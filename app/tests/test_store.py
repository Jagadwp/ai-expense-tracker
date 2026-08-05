import psycopg
import pytest

from app.config import get_settings
from app.store import NotFoundError, Store


@pytest.fixture
async def store():
    settings = get_settings()
    conn = await psycopg.AsyncConnection.connect(settings.database_url)
    try:
        # Isolate each test: start clean, clean up afterwards.
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM oauth_tokens WHERE user_id LIKE 'test-%'")
        await conn.commit()

        yield Store(conn)

        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM oauth_tokens WHERE user_id LIKE 'test-%'")
        await conn.commit()
    finally:
        await conn.close()


async def test_get_token_not_found(store):
    with pytest.raises(NotFoundError):
        await store.get_token("test-missing-user")


async def test_save_and_get_token(store):
    await store.save_token("test-user-1", b"encrypted-bytes", "user1@gmail.com")

    token = await store.get_token("test-user-1")

    assert token.user_id == "test-user-1"
    assert token.encrypted_token == b"encrypted-bytes"
    assert token.gmail_email == "user1@gmail.com"
    assert token.last_synced_at is None


async def test_save_token_upserts_on_conflict(store):
    await store.save_token("test-user-2", b"old-bytes", "old@gmail.com")
    await store.save_token("test-user-2", b"new-bytes", "new@gmail.com")

    token = await store.get_token("test-user-2")

    assert token.encrypted_token == b"new-bytes"
    assert token.gmail_email == "new@gmail.com"


async def test_delete_token(store):
    await store.save_token("test-user-3", b"bytes", "user3@gmail.com")
    await store.delete_token("test-user-3")

    with pytest.raises(NotFoundError):
        await store.get_token("test-user-3")


async def test_delete_nonexistent_token_is_noop(store):
    await store.delete_token("test-user-does-not-exist")  # should not raise


async def test_touch_last_synced(store):
    await store.save_token("test-user-4", b"bytes", "user4@gmail.com")
    await store.touch_last_synced("test-user-4")

    token = await store.get_token("test-user-4")

    assert token.last_synced_at is not None
