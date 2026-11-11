CREDS = {"email": "asha@example.com", "password": "s3cret-pass"}


async def _register_and_login(client) -> str:
    resp = await client.post("/auth/register", json={**CREDS, "name": "Asha"})
    assert resp.status_code == 201, resp.text
    resp = await client.post(
        "/auth/jwt/login", data={"username": CREDS["email"], "password": CREDS["password"]}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def test_register_login_and_me(client):
    token = await _register_and_login(client)

    resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    me = resp.json()
    assert me["email"] == CREDS["email"]
    assert me["name"] == "Asha"
    assert "hashed_password" not in me


async def test_duplicate_registration_rejected(client):
    await client.post("/auth/register", json=CREDS)
    resp = await client.post("/auth/register", json=CREDS)
    assert resp.status_code == 400


async def test_wrong_password_rejected(client):
    await client.post("/auth/register", json=CREDS)
    resp = await client.post("/auth/jwt/login", data={"username": CREDS["email"], "password": "wrong"})
    assert resp.status_code == 400


async def test_me_requires_token(client):
    assert (await client.get("/users/me")).status_code == 401
