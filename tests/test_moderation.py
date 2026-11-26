"""Doctor verification, reports, blocking, suspension."""
from conftest import JPEG_DATA_URL


def test_verification_flow(server, admin, uniq):
    doc, pat = server.client(), server.client()
    doc.signup("doctor", "Dr V", uniq())
    lid = doc.profile("Verify Clinic")
    pat.signup("patient", "P", uniq())
    good = {"council": "National Medical Commission (NMC)", "reg_no": "DMC/12345", "reg_year": 2018, "qualification": "MBBS", "confirm": True}
    assert pat.post("/api/m/verify/submit", good)[0] in (401, 403)
    assert doc.post("/api/m/verify/submit", dict(good, council="Fake council"))[0] == 400
    assert doc.post("/api/m/verify/submit", dict(good, reg_no="<script>"))[0] == 400
    assert doc.post("/api/m/verify/submit", dict(good, certificate=JPEG_DATA_URL))[0] == 200
    q = admin.post("/api/verify/list")[1]["created"]["verifications"]
    mid = next(v["member_id"] for v in q if v["listing_name"] == "Verify Clinic")
    assert doc.get(f"/api/verify/cert/{mid}")[0] == 404
    s, body, _ = admin.get(f"/api/verify/cert/{mid}")
    assert s == 200 and body[:2] == b"\xff\xd8"
    assert admin.post("/api/verify/decide", {"member_id": mid, "approve": False, "reason": "no"})[0] == 400
    assert admin.post("/api/verify/decide", {"member_id": mid, "approve": True})[0] == 200
    listing = next(x for x in server.client().post("/api/m/me")[1]["listings"] if x["id"] == lid)
    assert listing["verified"] is True


def test_reports_block_suspend(server, admin, uniq):
    doc, pat, pat2 = server.client(), server.client(), server.client()
    doc_email = uniq("doc")
    did = doc.signup("doctor", "Dr Rude", doc_email)
    lid = doc.profile("Rude Clinic")
    pid = pat.signup("patient", "P1", uniq())
    pat2.signup("patient", "P2", uniq())
    pat.post("/api/m/send", {"listing_id": lid, "body": "Hello"})
    doc.post("/api/m/send", {"to": pid, "body": "You are stupid"})
    assert server.client().post("/api/m/report", {"type": "listing", "id": lid, "reason": "fake"})[0] == 401
    assert pat.post("/api/m/report", {"type": "listing", "id": lid, "reason": "other"})[0] == 400  # needs details
    assert pat.post("/api/m/report", {"type": "member", "id": did, "reason": "abuse", "block": True})[0] == 200
    assert doc.post("/api/m/send", {"to": pid, "body": "again"})[0] == 403  # blocked
    assert pat2.post("/api/m/report", {"type": "listing", "id": lid, "reason": "wrong"})[0] == 200
    G = {(g["type"], g["target_id"]): g for g in admin.post("/api/report/list")[1]["created"]["reports"] if g["status"] == "open"}
    assert any("stupid" in m["body"] for m in G[("member", did)]["evidence"]["messages"])
    assert admin.post("/api/report/decide", {"id": G[("listing", lid)]["id"], "action": "hide"})[0] == 200
    assert all(x["id"] != lid for x in server.client().post("/api/m/me")[1]["listings"])
    assert admin.post("/api/report/decide", {"id": G[("member", did)]["id"], "action": "suspend"})[0] == 200
    assert doc.post("/api/m/me")[1].get("me") is None
    s, j = server.client().post("/api/m/login", {"email": doc_email, "password": "Pass123456!"})
    assert s == 403 and "suspended" in j["error"]
    assert any("Thanks for your report" in n["title"] for n in pat.post("/api/m/notifs")[1]["notifs"])
    assert pat.post("/api/report/list")[0] in (401, 403)
