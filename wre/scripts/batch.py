"""Early fixed five-site discover comparison (kept as a first-pass record)."""

from wre_client_akamai import AkamaiClient

SITES = [
    ("https://www.flaticon.com/", "user case: interstitial B"),
    ("https://www.nh-hotels.com/", "user case: interstitial canonical"),
    ("https://www.nike.com/", "public: likely classic"),
    ("https://www.adidas.com/us", "public: likely classic"),
    ("https://www.akamai.com/", "akamai own site"),
]

for url, tag in SITES:
    try:
        with AkamaiClient.open({"page_url": url}, startup_timeout=60) as c:
            d = c.discover({}, deadline=60)
            surf = d["surface"]
            sensor = surf["sensor"]["kind"] if surf["sensor"] else None
            cfg = surf["config"] or {}
            print("%-34s %-28s status=%-4s protected=%-5s sensor=%-12s challenge=%s"
                  % (url, tag, d["status"], d["protected"], sensor, surf["challenge_page"]))
            if cfg:
                print("   baza bits=%s flags=%s" % (cfg.get("bits"), cfg.get("flags")))
    except Exception as e:
        print("%-34s %-28s ERR %s: %s" % (url, tag, type(e).__name__, str(e)[:160]))
