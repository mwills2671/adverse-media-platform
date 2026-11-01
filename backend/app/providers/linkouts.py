"""Link-outs: sources NOT machine-searched. Shown for manual checking only; never mixed into findings."""
from urllib.parse import quote_plus


def link_outs(name: str, subject_type: str) -> dict:
    q = quote_plus(name)
    adverse = [
        {"id": "fca_register", "name": "FCA Financial Services Register", "url": f"https://register.fca.org.uk/s/search?q={q}&type={'Companies' if subject_type == 'entity' else 'Individuals'}",
         "note": "Link-out, not machine-searched (FCA Register API requires registration)."},
        {"id": "fca_warnings", "name": "FCA Warning List of unauthorised firms", "url": "https://www.fca.org.uk/consumers/warning-list-unauthorised-firms",
         "note": "Link-out, not machine-searched."},
        {"id": "companies_house_web", "name": "Companies House (web search)", "url": f"https://find-and-update.company-information.service.gov.uk/search?q={q}",
         "note": "Link-out. Machine search requires COMPANIES_HOUSE_API_KEY."},
        {"id": "courtlistener_web", "name": "CourtListener (web search)", "url": f"https://www.courtlistener.com/?q=%22{q}%22",
         "note": "Link-out. Machine search requires COURTLISTENER_API_TOKEN."},
        {"id": "bailii", "name": "BAILII (UK & Irish case law)", "url": "https://www.bailii.org/form/search_multidatabase.html",
         "note": "Link-out, not machine-searched."},
    ]
    sanctions_pep = [
        {"id": "opensanctions", "name": "OpenSanctions (sanctions/PEP reference)", "url": f"https://www.opensanctions.org/search/?q={q}",
         "note": "Reference only — sanctions/PEP screening is a separate module and is NOT performed here."},
        {"id": "uk_sanctions", "name": "UK Sanctions List search (OFSI)", "url": "https://sanctionssearchapp.ofsi.hmtreasury.gov.uk/",
         "note": "Reference only — not searched."},
        {"id": "ofac", "name": "OFAC Sanctions List Search", "url": "https://sanctionssearch.ofac.treas.gov/",
         "note": "Reference only — not searched."},
    ]
    return {"adverse_media_manual": adverse, "sanctions_pep_reference": sanctions_pep}
