"""Post-process deckshop_counters.py to add weak_or_no_counter lists."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOD_PATH = ROOT / "bot" / "data" / "deckshop_counters.py"


def main() -> None:
    spec = importlib.util.spec_from_file_location("deckshop_counters", MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)

    all_names = sorted(mod.DECKSHOP_COUNTERS.keys())
    for name, data in mod.DECKSHOP_COUNTERS.items():
        listed: set[str] = set()
        for block in (
            data.get("counters_vs_attack"),
            data.get("counters_vs_defense"),
        ):
            if block:
                listed |= set(block.get("strong") or [])
                listed |= set(block.get("partial") or [])
        data["weak_or_no_counter"] = sorted(n for n in all_names if n not in listed and n != name)
        data["anti_counter_count"] = len(data["weak_or_no_counter"])

    # rewrite via scraper writer
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from scrape_deckshop_counters import write_module

    slugs = [d["slug"] for d in mod.DECKSHOP_COUNTERS.values()]
    write_module(mod.DECKSHOP_COUNTERS, slugs)
    print("Updated anti-counter fields for", len(all_names), "cards")


if __name__ == "__main__":
    main()
