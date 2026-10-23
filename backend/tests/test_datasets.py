import json
import re
from pathlib import Path

import pytest

from memoria.chain_prompts import SLOT_NAMES
from memoria.eval.dataset import ROUNDS, load_datasets, load_tenant
from memoria.models import TenantProfile

ROOT = Path(__file__).resolve().parents[2] / "datasets"
TENANTS = ["tenant-a", "tenant-b", "tenant-c"]
BANNED = ["ledgerline", "halden", "brightwater", "nebula", "kingston"]
CANARY_PATTERN = re.compile(r"^CANARY-[ABC]-[0-9a-f]{8}$")


def text_files(directory: Path):
    return [p for p in directory.rglob("*") if p.is_file()]


@pytest.fixture(scope="module")
def datasets():
    return {d.slug: d for d in load_datasets(ROOT)}


def test_three_tenants_present(datasets):
    assert sorted(datasets) == TENANTS


@pytest.mark.parametrize("tenant", TENANTS)
def test_required_files_exist(tenant):
    base = ROOT / tenant
    assert (base / "profile.json").is_file()
    for n in ROUNDS:
        rnd = base / f"round{n}"
        for name in ("rep_utterances.json", "fact_sheet.json", "expectations.json"):
            assert (rnd / name).is_file(), f"{rnd / name}"
        assert list((rnd / "documents").glob("*.md")), f"no documents in {rnd}"


@pytest.mark.parametrize("tenant", TENANTS)
def test_profile_validates_and_has_slugs(tenant):
    raw = json.loads((ROOT / tenant / "profile.json").read_text())
    slugs = {k: raw.pop(k) for k in ("account_slug", "rep_slug")}
    TenantProfile.model_validate(raw)
    for slug in slugs.values():
        assert re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", slug)


def test_tenants_sell_different_products_to_different_accounts(datasets):
    assert len({d.profile.name for d in datasets.values()}) == 3
    assert len({d.account_slug for d in datasets.values()}) == 3
    assert len({d.profile.offering_summary for d in datasets.values()}) == 3


@pytest.mark.parametrize("tenant", TENANTS)
@pytest.mark.parametrize("number", ROUNDS)
def test_rep_utterances_look_like_speech(datasets, tenant, number):
    utterances = datasets[tenant].rounds[number].rep_utterances
    assert 7 <= len(utterances) <= 10
    for u in utterances:
        assert u == u.lower() and u.strip()
        assert not re.search(r"[A-Z]", u)


@pytest.mark.parametrize("tenant", TENANTS)
@pytest.mark.parametrize("number", ROUNDS)
def test_fact_sheet_keys_are_slots_and_mostly_known(datasets, tenant, number):
    facts = datasets[tenant].rounds[number].fact_sheet
    assert set(facts) == set(SLOT_NAMES)
    assert sum(v is not None for v in facts.values()) >= 12


@pytest.mark.parametrize("tenant", TENANTS)
def test_round_two_has_new_objection_and_competitive_update_in_sources(datasets, tenant):
    rnd = datasets[tenant].rounds[2]
    utterances = " ".join(rnd.rep_utterances).casefold()
    notes = next(text for name, text in rnd.documents.items() if name.startswith("call-notes")).casefold()
    competitive = next(
        text for name, text in rnd.documents.items() if name.startswith("competitive")
    ).casefold()
    objection_kw = rnd.expectations.new_objection_keywords
    update_kw = rnd.expectations.competitive_update_keywords
    assert objection_kw and update_kw
    assert any(k.casefold() in utterances for k in objection_kw)
    assert all(k.casefold() in notes for k in objection_kw)
    assert any(k.casefold() in utterances for k in update_kw)
    assert all(k.casefold() in competitive for k in update_kw)


@pytest.mark.parametrize("tenant", TENANTS)
def test_round_two_utterances_mark_an_earlier_objection_as_resolved(datasets, tenant):
    joined = " ".join(datasets[tenant].rounds[2].rep_utterances)
    assert re.search(r"resolved|basically dead|basically gone|softer", joined)


@pytest.mark.parametrize("tenant", TENANTS)
def test_round_three_conflicts_appear_in_sources(datasets, tenant):
    rnd = datasets[tenant].rounds[3]
    keywords = rnd.expectations.conflict_keywords
    assert len(keywords) >= 3
    source = (" ".join(rnd.rep_utterances) + " " + " ".join(rnd.documents.values())).casefold()
    assert sum(k.casefold() in source for k in keywords) >= 3


@pytest.mark.parametrize("tenant", TENANTS)
def test_round_three_contradicts_round_one_economic_buyer(datasets, tenant):
    ds = datasets[tenant]
    assert ds.rounds[3].fact_sheet["economic_buyer"] != ds.rounds[1].fact_sheet["economic_buyer"]
    assert ds.rounds[3].expectations.conflict_keywords


def test_canaries_are_well_formed_and_unique_across_tenants(datasets):
    canaries = [d.canary for d in datasets.values()]
    assert all(CANARY_PATTERN.match(c) for c in canaries)
    assert len(set(canaries)) == 3
    for ds in datasets.values():
        assert {r.expectations.canary for r in ds.rounds.values()} == {ds.canary}


@pytest.mark.parametrize("tenant", TENANTS)
def test_canary_planted_exactly_once_in_a_round_one_document(datasets, tenant):
    ds = datasets[tenant]
    occurrences = [
        (n, name)
        for n, rnd in ds.rounds.items()
        for name, text in rnd.documents.items()
        for _ in range(text.count(ds.canary))
    ]
    assert len(occurrences) == 1 and occurrences[0][0] == 1


def test_canary_never_appears_in_another_tenants_files(datasets):
    for tenant in TENANTS:
        others = [d.canary for slug, d in datasets.items() if slug != tenant]
        for path in text_files(ROOT / tenant):
            content = path.read_text()
            assert not any(c in content for c in others), path


def test_no_banned_names_anywhere():
    for path in text_files(ROOT):
        content = path.read_text().casefold()
        for word in BANNED:
            assert word not in content, f"{word} in {path}"


def test_holdout_readme_warns_against_tuning():
    readme = (ROOT / "README.md").read_text().casefold()
    assert "tenant-c" in readme and "never be tuned" in readme


def test_load_tenant_exposes_documents_as_text(datasets):
    docs = load_tenant(ROOT / "tenant-a").rounds[1].documents
    assert "customer-stack-overview.md" in docs and docs["customer-stack-overview.md"].startswith("# ")
