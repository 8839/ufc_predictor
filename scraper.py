"""UFCStats.com scraping logic."""

import re
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

import database
import utils
from config import BASE_URL, REQUEST_DELAY, REFRESH_WINDOW_DAYS


SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "UFC-Fight-Predictor/1.0 (educational project)"
})


def _get(url: str) -> BeautifulSoup:
    """Fetch a URL and return parsed BeautifulSoup, respecting rate limit."""
    time.sleep(REQUEST_DELAY)
    resp = SESSION.get(url, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


# ---------------------------------------------------------------------------
# Fighter Index
# ---------------------------------------------------------------------------

def scrape_fighter_index() -> list[dict]:
    """Scrape all fighter index pages (a-z) and return basic fighter info."""
    fighters = []
    for char in "abcdefghijklmnopqrstuvwxyz":
        url = f"{BASE_URL}/statistics/fighters?char={char}&page=all"
        print(f"  Scraping fighter index: {char}...", flush=True)
        soup = _get(url)

        rows = soup.select("table.b-statistics__table tbody tr")
        for row in rows:
            cols = row.select("td")
            if len(cols) < 3:
                continue
            link = row.select_one("a.b-link")
            if not link:
                continue
            href = link.get("href", "")
            fighter_id = href.rstrip("/").split("/")[-1]
            if not fighter_id:
                continue

            first_name = cols[0].get_text(strip=True)
            last_name = cols[1].get_text(strip=True)
            name = f"{first_name} {last_name}".strip()
            nickname = cols[2].get_text(strip=True) if len(cols) > 2 else ""

            fighters.append({
                "id": fighter_id,
                "name": name,
                "nickname": nickname if nickname and nickname != "--" else None,
            })
    print(f"  Found {len(fighters)} fighters in index.", flush=True)
    return fighters


# ---------------------------------------------------------------------------
# Fighter Detail
# ---------------------------------------------------------------------------

def scrape_fighter_detail(fighter_id: str) -> dict:
    """Scrape a single fighter's detail page for stats and bio."""
    url = f"{BASE_URL}/fighter-details/{fighter_id}"
    soup = _get(url)

    info = {"id": fighter_id, "last_updated": datetime.utcnow().isoformat()}

    # Name
    name_el = soup.select_one("span.b-content__title-highlight")
    if name_el:
        info["name"] = name_el.get_text(strip=True)

    # Nickname
    nick_el = soup.select_one("p.b-content__Nickname")
    if nick_el:
        nick = nick_el.get_text(strip=True)
        info["nickname"] = nick if nick and nick != "--" else None

    # Record
    record_el = soup.select_one("span.b-content__title-record")
    if record_el:
        record_text = record_el.get_text(strip=True).replace("Record:", "").strip()
        wins, losses, draws, nc = utils.parse_record(record_text)
        info["wins"] = wins
        info["losses"] = losses
        info["draws"] = draws
        info["no_contests"] = nc

    # Bio details (height, weight, reach, stance, DOB)
    bio_items = soup.select("ul.b-list__box-list li.b-list__box-list-item")
    for item in bio_items:
        text = item.get_text(strip=True)
        if text.startswith("Height:"):
            info["height_inches"] = utils.parse_height(text.replace("Height:", ""))
        elif text.startswith("Weight:"):
            info["weight_lbs"] = utils.parse_weight(text.replace("Weight:", ""))
        elif text.startswith("Reach:"):
            info["reach_inches"] = utils.parse_reach(text.replace("Reach:", ""))
        elif text.startswith("STANCE:"):
            stance = text.replace("STANCE:", "").strip()
            info["stance"] = stance if stance and stance != "--" else None
        elif text.startswith("DOB:"):
            info["dob"] = utils.parse_date(text.replace("DOB:", ""))

    # Career stats
    stat_boxes = soup.select("div.b-list__info-box-left li, div.b-list__info-box li")
    for box in stat_boxes:
        text = box.get_text(" ", strip=True)
        if "SLpM" in text:
            info["sig_strikes_landed_per_min"] = utils.parse_stat_float(
                text.split(":")[-1]
            )
        elif "Str. Acc" in text:
            info["sig_strike_accuracy"] = utils.parse_percentage(
                text.split(":")[-1]
            )
        elif "SApM" in text:
            info["sig_strikes_absorbed_per_min"] = utils.parse_stat_float(
                text.split(":")[-1]
            )
        elif "Str. Def" in text:
            info["sig_strike_defense"] = utils.parse_percentage(
                text.split(":")[-1]
            )
        elif "TD Avg" in text:
            info["takedown_avg_per_15min"] = utils.parse_stat_float(
                text.split(":")[-1]
            )
        elif "TD Acc" in text:
            info["takedown_accuracy"] = utils.parse_percentage(
                text.split(":")[-1]
            )
        elif "TD Def" in text:
            info["takedown_defense"] = utils.parse_percentage(
                text.split(":")[-1]
            )
        elif "Sub. Avg" in text:
            info["submission_avg_per_15min"] = utils.parse_stat_float(
                text.split(":")[-1]
            )

    # Set defaults for missing numeric fields
    for field in [
        "wins", "losses", "draws", "no_contests", "height_inches",
        "weight_lbs", "reach_inches", "sig_strikes_landed_per_min",
        "sig_strike_accuracy", "sig_strikes_absorbed_per_min",
        "sig_strike_defense", "takedown_avg_per_15min", "takedown_accuracy",
        "takedown_defense", "submission_avg_per_15min",
    ]:
        info.setdefault(field, None)
    info.setdefault("nickname", None)
    info.setdefault("stance", None)
    info.setdefault("dob", None)

    return info


# ---------------------------------------------------------------------------
# Event List
# ---------------------------------------------------------------------------

def scrape_event_list() -> list[dict]:
    """Scrape the completed events list. Returns list of {id, name, date, url}."""
    url = f"{BASE_URL}/statistics/events/completed?page=all"
    print("  Scraping event list...", flush=True)
    soup = _get(url)

    events = []
    rows = soup.select("table.b-statistics__table-events tbody tr")
    for row in rows:
        link = row.select_one("a.b-link")
        if not link:
            continue
        href = link.get("href", "")
        event_id = href.rstrip("/").split("/")[-1]
        name = link.get_text(strip=True)
        date_cell = row.select_one("span.b-statistics__date")
        event_date = utils.parse_date(date_cell.get_text(strip=True)) if date_cell else None
        events.append({
            "id": event_id,
            "name": name,
            "date": event_date,
            "url": href,
        })
    print(f"  Found {len(events)} events.", flush=True)
    return events


# ---------------------------------------------------------------------------
# Event Detail (fights on a card)
# ---------------------------------------------------------------------------

def scrape_event_detail(event_id: str, event_name: str, event_date: str) -> list[dict]:
    """Scrape an event detail page for all fights on the card."""
    url = f"{BASE_URL}/event-details/{event_id}"
    soup = _get(url)

    fights = []
    rows = soup.select("table.b-fight-details__table tbody tr")
    for row in rows:
        fight_link = row.get("data-link", "")
        if not fight_link:
            continue
        fight_id = fight_link.rstrip("/").split("/")[-1]

        cols = row.select("td")
        if len(cols) < 10:
            continue

        # Fighters
        fighter_links = cols[1].select("a")
        if len(fighter_links) < 2:
            continue
        f1_href = fighter_links[0].get("href", "")
        f2_href = fighter_links[1].get("href", "")
        f1_id = f1_href.rstrip("/").split("/")[-1]
        f2_id = f2_href.rstrip("/").split("/")[-1]

        # Winner — indicated by a green flag element in the first column
        winner_id = None
        win_flag = cols[0].select_one("a.b-flag_style_green")
        if win_flag:
            # Green flag present means fighter1 (first listed) won
            winner_id = f1_id

        # Method
        method_parts = [p.get_text(strip=True) for p in cols[7].select("p")]
        win_method = method_parts[0] if method_parts else None
        win_method_detail = method_parts[1] if len(method_parts) > 1 else None

        # Round
        round_text = cols[8].get_text(strip=True)
        finish_round = int(round_text) if round_text.isdigit() else None

        # Time
        finish_time = cols[9].get_text(strip=True) or None

        # Weight class
        wc_parts = [p.get_text(strip=True) for p in cols[6].select("p")]
        weight_class = wc_parts[0] if wc_parts else None

        # Title fight detection — indicated by a belt.png image in the weight class column
        is_title = 0
        belt_img = cols[6].select_one("img[src*='belt']")
        if belt_img:
            is_title = 1

        # Scheduled rounds — title fights and main events are typically 5
        num_rounds = 5 if is_title else 3

        fights.append({
            "id": fight_id,
            "event_name": event_name,
            "event_date": event_date,
            "fighter1_id": f1_id,
            "fighter2_id": f2_id,
            "winner_id": winner_id,
            "win_method": win_method,
            "win_method_detail": win_method_detail,
            "finish_round": finish_round,
            "finish_time": finish_time,
            "is_title_fight": is_title,
            "weight_class": weight_class,
            "num_rounds": num_rounds,
        })

    return fights


# ---------------------------------------------------------------------------
# Fight Detail (round-by-round stats)
# ---------------------------------------------------------------------------

def scrape_fight_detail(fight_id: str) -> list[dict]:
    """Scrape round-by-round stats for a fight. Returns two stat dicts (one per fighter)."""
    url = f"{BASE_URL}/fight-details/{fight_id}"
    soup = _get(url)

    totals_section = soup.select("table.b-fight-details__table.js-fight-table")
    if not totals_section:
        return []

    # The first table contains the totals row
    table = totals_section[0]
    rows = table.select("tbody tr")
    if not rows:
        return []

    # Get fighter IDs from links in the first totals row
    first_row = rows[0]
    cols = first_row.select("td")
    if len(cols) < 10:
        return []

    fighter_links = cols[0].select("a")
    if len(fighter_links) < 2:
        return []

    stats_list = []
    for i, link in enumerate(fighter_links[:2]):
        fighter_id = link.get("href", "").rstrip("/").split("/")[-1]

        # Each fighter has a <p> in each column — first <p> = fighter 1, second = fighter 2
        def _get_col_text(col_idx):
            ps = cols[col_idx].select("p")
            if i < len(ps):
                return ps[i].get_text(strip=True)
            return ""

        kd = _get_col_text(1)
        sig_str = _get_col_text(2)
        total_str = _get_col_text(4)
        td_str = _get_col_text(5)
        sub_att = _get_col_text(7)
        rev = _get_col_text(8)
        ctrl = _get_col_text(9)

        sig_landed, sig_attempted = utils.parse_strikes(sig_str)
        total_landed, total_attempted = utils.parse_strikes(total_str)
        td_landed, td_attempted = utils.parse_strikes(td_str)

        stats_list.append({
            "fight_id": fight_id,
            "fighter_id": fighter_id,
            "knockdowns": int(kd) if kd.isdigit() else 0,
            "sig_strikes_landed": sig_landed,
            "sig_strikes_attempted": sig_attempted,
            "total_strikes_landed": total_landed,
            "total_strikes_attempted": total_attempted,
            "takedowns_landed": td_landed,
            "takedowns_attempted": td_attempted,
            "submission_attempts": int(sub_att) if sub_att.isdigit() else 0,
            "reversals": int(rev) if rev.isdigit() else 0,
            "control_time_seconds": utils.parse_control_time(ctrl),
        })

    return stats_list


# ---------------------------------------------------------------------------
# Full Scrape Orchestration
# ---------------------------------------------------------------------------

def _print(msg: str):
    """Print with immediate flush for background process visibility."""
    print(msg, flush=True)


def full_scrape():
    """Perform a full scrape of all fighters, events, fights, and fight stats."""
    database.init_db()
    _print("\n=== FULL SCRAPE ===\n")

    # 1. Scrape fighter index
    _print("[1/4] Scraping fighter index...")
    index_fighters = scrape_fighter_index()

    # 2. Scrape each fighter's detail page
    _print(f"\n[2/4] Scraping {len(index_fighters)} fighter detail pages...")
    for i, f in enumerate(index_fighters, 1):
        if i % 50 == 0:
            _print(f"  {i}/{len(index_fighters)} fighters scraped...")
        try:
            detail = scrape_fighter_detail(f["id"])
            database.upsert_fighter(detail)
        except Exception as e:
            _print(f"  Warning: failed to scrape fighter {f['name']} ({f['id']}): {e}")

    # 3. Scrape events and fights
    _print("\n[3/4] Scraping events and fights...")
    events = scrape_event_list()
    fight_ids = []
    for i, event in enumerate(events, 1):
        if i % 20 == 0:
            _print(f"  {i}/{len(events)} events scraped...")
        try:
            fights = scrape_event_detail(event["id"], event["name"], event["date"])
            for fight in fights:
                database.upsert_fight(fight)
                fight_ids.append(fight["id"])
        except Exception as e:
            _print(f"  Warning: failed to scrape event {event['name']}: {e}")

    # 4. Scrape fight details (stats)
    _print(f"\n[4/4] Scraping {len(fight_ids)} fight stat pages...")
    for i, fid in enumerate(fight_ids, 1):
        if i % 100 == 0:
            _print(f"  {i}/{len(fight_ids)} fight stats scraped...")
        try:
            stats = scrape_fight_detail(fid)
            for s in stats:
                database.upsert_fight_stats(s)
        except Exception as e:
            _print(f"  Warning: failed to scrape fight stats {fid}: {e}")

    _print("\n=== FULL SCRAPE COMPLETE ===\n")


def refresh_scrape():
    """Incremental refresh — only update recently active fighters."""
    database.init_db()
    print("\n=== INCREMENTAL REFRESH ===\n")

    cutoff = (datetime.utcnow() - timedelta(days=REFRESH_WINDOW_DAYS)).strftime("%Y-%m-%d")

    # Get events within refresh window
    events = scrape_event_list()
    recent_events = [e for e in events if e["date"] and e["date"] >= cutoff]
    print(f"Found {len(recent_events)} events in the last {REFRESH_WINDOW_DAYS} days.")

    fighter_ids_seen = set()
    for event in recent_events:
        try:
            fights = scrape_event_detail(event["id"], event["name"], event["date"])
            for fight in fights:
                database.upsert_fight(fight)
                fighter_ids_seen.add(fight["fighter1_id"])
                fighter_ids_seen.add(fight["fighter2_id"])
                # Scrape fight stats
                try:
                    stats = scrape_fight_detail(fight["id"])
                    for s in stats:
                        database.upsert_fight_stats(s)
                except Exception as e:
                    print(f"  Warning: fight stats {fight['id']}: {e}")
        except Exception as e:
            print(f"  Warning: event {event['name']}: {e}")

    # Refresh fighter details for recently active fighters
    print(f"\nRefreshing {len(fighter_ids_seen)} recently active fighters...")
    for fid in fighter_ids_seen:
        try:
            detail = scrape_fighter_detail(fid)
            database.upsert_fighter(detail)
        except Exception as e:
            print(f"  Warning: fighter {fid}: {e}")

    print("\n=== REFRESH COMPLETE ===\n")
