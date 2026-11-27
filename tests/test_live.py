"""Live location sharing: private link, updates, expiry, stop, and no account needed."""


def test_share_update_view_and_stop(server):
    me, family, stranger = server.client(), server.client(), server.client()
    s, j = me.post("/api/live/start", {"lat": 34.0837, "lon": 74.7973, "acc": 8, "speed": 12.5, "mode": "car", "minutes": 60, "name": "Ram <b>"})
    assert s == 200 and j["url"].endswith("#live/" + j["id"]) and len(j["key"]) > 20
    view = lambda c: (lambda r: (r[0], __import__("json").loads(r[1])))(c.get("/api/live/v/" + j["id"]))
    s, v = view(family)
    assert s == 200 and v["mode"] == "car" and abs(v["lat"] - 34.0837) < 1e-6 and v["name"] == "Ram b"  # no HTML
    assert "key" not in v and "key_hash" not in v
    assert me.post("/api/live/update", {"key": j["key"], "lat": 34.09, "lon": 74.80, "speed": 70, "mode": "train"})[0] == 200
    s, v = view(family)
    assert v["lat"] == 34.09 and v["mode"] == "train" and v["speed"] == 70
    # someone with only the view link can't move the marker
    assert stranger.post("/api/live/update", {"key": j["id"], "lat": 1, "lon": 1})[0] == 410
    assert stranger.get("/api/live/v/wrong-id-123456")[0] == 404
    assert me.post("/api/live/stop", {"key": j["key"]})[0] == 200
    assert family.get("/api/live/v/" + j["id"])[0] == 404
    assert me.post("/api/live/update", {"key": j["key"], "lat": 34.1, "lon": 74.8})[0] == 410


def test_bad_input_and_expiry(server):
    c = server.client()
    assert c.post("/api/live/start", {"lat": 200, "lon": 0})[0] == 400
    assert c.post("/api/live/start", {"lon": 0})[0] == 400
    s, j = c.post("/api/live/start", {"lat": 1, "lon": 1, "mode": "spaceship", "minutes": 99999})
    assert s == 200 and j["expires"] - __import__("time").time() * 1000 <= 24 * 3600 * 1000 + 5000
    db = server.db()
    db.execute("UPDATE live_shares SET expires=1")
    db.commit()
    assert c.get("/api/live/v/" + j["id"])[0] == 404
