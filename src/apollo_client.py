import os
import requests
from typing import Any, Dict, Iterator, List, Optional


class ApolloCreditsExhausted(RuntimeError):
    """Apollo rejected the call because the team has no lead credits left."""


class ApolloClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.apollo.io/v1"
        self.headers = {
            "Cache-Control": "no-cache",
            "Content-Type": "application/json",
            "X-Api-Key": self.api_key
        }

    def search_people(self, data, page=1):
        """
        Search for people using Apollo's search endpoint.
        """
        url = "https://api.apollo.io/api/v1/mixed_people/api_search"
        data["page"] = page
        
        try:
            response = requests.post(url, headers=self.headers, json=data)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error searching people: {e}")
            if 'response' in locals() and response is not None:
                print(response.text)
            return None

    def enrich_person(self, person_id):
        """
        Enrich a single person by their Apollo ID to get full contact details
        (email, phone, LinkedIn, etc.).
        Uses the /v1/people/match endpoint with person_id.
        """
        url = "https://api.apollo.io/v1/people/match"
        payload = {"id": person_id}

        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return data.get("person", {})
        except requests.exceptions.RequestException as e:
            body = ""
            if "response" in locals() and response is not None:
                body = response.text or ""
            if "CREDITS_EXHAUSTED" in body or "insufficient credits" in body.lower():
                raise ApolloCreditsExhausted("Apollo lead credits exhausted") from e
            print(f"  Enrichment failed for {person_id}: {e}")
            return None

    def search_companies(self, data, page=1):
        """
        Search for companies using Apollo's organizations/search endpoint.
        """
        url = f"{self.base_url}/organizations/search"
        data = dict(data)
        data["page"] = page

        try:
            response = requests.post(url, headers=self.headers, json=data)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error searching companies: {e}")
            if "response" in locals() and response is not None:
                print(response.text)
            return None

    @staticmethod
    def orgs_from_search_response(data: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not data:
            return []
        for key in ("organizations", "accounts"):
            rows = data.get(key)
            if isinstance(rows, list):
                return rows
        return []

    def search_organization_by_name(
        self,
        name: str,
        *,
        page: int = 1,
        per_page: int = 15,
        organization_locations: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Apollo organizations/search by employer name (legal-name discovery)."""
        payload: Dict[str, Any] = {
            "q_organization_name": (name or "").strip(),
            "page": page,
            "per_page": per_page,
        }
        if organization_locations:
            payload["organization_locations"] = organization_locations
        return self.search_companies(payload, page=page)

    def search_organization_by_domain(
        self,
        domain: str,
        *,
        page: int = 1,
        per_page: int = 15,
        organization_locations: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Apollo organizations/search by primary domain (best for shelf brands)."""
        d = (domain or "").strip().lower()
        d = d.replace("https://", "").replace("http://", "").split("/")[0].removeprefix("www.")
        payload: Dict[str, Any] = {
            "q_organization_domains": d,
            "page": page,
            "per_page": per_page,
        }
        if organization_locations:
            payload["organization_locations"] = organization_locations
        return self.search_companies(payload, page=page)

    def search_organizations(
        self,
        *,
        org_keyword_tags: List[str],
        organization_locations: List[str],
        employee_ranges: List[str],
        page: int = 1,
        per_page: int = 100,
        revenue_min: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Organization search by keyword tags + HQ location + size (no company name)."""
        payload: Dict[str, Any] = {
            "page": page,
            "per_page": per_page,
            "q_organization_keyword_tags": org_keyword_tags,
            "organization_locations": organization_locations,
            "organization_num_employees_ranges": employee_ranges,
        }
        if revenue_min and revenue_min > 0:
            payload["revenue_range[min]"] = revenue_min
        return self.search_companies(payload, page=page)

    def iter_organization_ids(
        self,
        *,
        org_keyword_tags: List[str],
        organization_locations: List[str],
        employee_ranges: List[str],
        max_pages: int = 2,
        per_page: int = 100,
        revenue_min: Optional[int] = None,
    ) -> Iterator[str]:
        """Yield Apollo organization ids across up to max_pages."""
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            data = self.search_organizations(
                org_keyword_tags=org_keyword_tags,
                organization_locations=organization_locations,
                employee_ranges=employee_ranges,
                page=page,
                per_page=per_page,
                revenue_min=revenue_min,
            )
            orgs = self.orgs_from_search_response(data)
            if not orgs:
                break
            for org in orgs:
                oid = org.get("id") or org.get("organization_id")
                if oid and str(oid) not in seen:
                    seen.add(str(oid))
                    yield str(oid)
            pagination = (data or {}).get("pagination") or {}
            if page >= pagination.get("total_pages", page):
                break

    def search_people_by_orgs(
        self,
        *,
        organization_ids: List[str],
        person_titles: List[str],
        person_seniorities: List[str],
        page: int = 1,
        per_page: int = 25,
        person_locations: Optional[List[str]] = None,
        organization_locations: Optional[List[str]] = None,
        require_verified_email: bool = True,
        include_similar_titles: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """People at specific employers (no q_organization_name)."""
        payload: Dict[str, Any] = {
            "page": page,
            "per_page": per_page,
            "organization_ids": organization_ids,
            "person_titles": person_titles,
            "person_seniorities": person_seniorities,
            "include_similar_titles": include_similar_titles,
        }
        if require_verified_email:
            payload["contact_email_status"] = ["verified"]
        if person_locations:
            payload["person_locations"] = person_locations
        if organization_locations:
            payload["organization_locations"] = organization_locations
        return self.search_people(payload, page=page)


def _people_from_response(data: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not data:
        return []
    for key in ("people", "contacts"):
        rows = data.get(key)
        if isinstance(rows, list):
            return rows
    return []


def with_retry(
    fn,
    *,
    max_attempts: int = 5,
    base_sleep_s: float = 1.0,
    label: str = "apollo",
):
    """Retry None responses and transient errors. Credits exhausted is not retried."""
    import time

    last = None
    for attempt in range(1, max_attempts + 1):
        try:
            last = fn()
            if last is not None:
                return last
            if attempt < max_attempts:
                time.sleep(base_sleep_s * (2 ** (attempt - 1)))
        except ApolloCreditsExhausted:
            raise
        except Exception as exc:  # noqa: BLE001 - volume search survives a transient blip
            if attempt >= max_attempts:
                raise
            print(f"  [{label}] error {exc!r}, retry {attempt}/{max_attempts}")
            time.sleep(base_sleep_s * (2 ** (attempt - 1)))
    return last


def dedupe_people_by_id(people) -> List[Dict[str, Any]]:
    from venue_rental_qa import normalize_person_id

    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for person in people:
        pid = normalize_person_id(person)
        if not pid or pid in seen:
            continue
        seen.add(pid)
        out.append(person)
    return out


def search_people_direct(
    apollo,
    *,
    titles: Optional[List[str]] = None,
    locations: Optional[List[str]] = None,
    seniorities: Optional[List[str]] = None,
    page: int = 1,
    per_page: int = 100,
    require_verified_email: bool = True,
    include_similar_titles: bool = True,
    revenue_min: Optional[int] = None,
    employee_ranges: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Direct people search by title and location. No organization_ids."""
    from venue_rental_config import VENUE_RENTAL_PERSON_SENIORITIES, VENUE_RENTAL_PERSON_TITLES

    payload: Dict[str, Any] = {
        "page": page,
        "per_page": per_page,
        "person_titles": titles or VENUE_RENTAL_PERSON_TITLES,
        "person_seniorities": seniorities or VENUE_RENTAL_PERSON_SENIORITIES,
        "include_similar_titles": include_similar_titles,
    }
    if locations:
        payload["person_locations"] = locations
    if require_verified_email:
        payload["contact_email_status"] = ["verified"]
    if revenue_min and revenue_min > 0:
        payload["revenue_range[min]"] = int(revenue_min)
    if employee_ranges:
        payload["organization_num_employees_ranges"] = employee_ranges

    return with_retry(lambda: apollo.search_people(payload, page=page), label=f"people_direct p{page}")


def iter_people_direct(
    apollo,
    *,
    titles: Optional[List[str]] = None,
    locations: Optional[List[str]] = None,
    seniorities: Optional[List[str]] = None,
    max_pages: int = 15,
    per_page: int = 100,
    require_verified_email: bool = True,
    include_similar_titles: bool = True,
    revenue_min: Optional[int] = None,
    employee_ranges: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    people: List[Dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        data = search_people_direct(
            apollo,
            titles=titles,
            locations=locations,
            seniorities=seniorities,
            page=page,
            per_page=per_page,
            require_verified_email=require_verified_email,
            include_similar_titles=include_similar_titles,
            revenue_min=revenue_min,
            employee_ranges=employee_ranges,
        )
        batch = _people_from_response(data)
        if not batch:
            break
        people.extend(batch)
        total_pages = int(((data or {}).get("pagination") or {}).get("total_pages") or page)
        if page >= total_pages:
            break
    return dedupe_people_by_id(people)


def search_orgs_then_people(
    apollo,
    *,
    org_keyword_tags: Optional[List[str]] = None,
    org_locations: Optional[List[str]] = None,
    person_titles: Optional[List[str]] = None,
    person_seniorities: Optional[List[str]] = None,
    person_locations: Optional[List[str]] = None,
    employee_ranges: Optional[List[str]] = None,
    revenue_min: Optional[int] = None,
    include_similar_titles: bool = True,
    max_org_pages: int = 3,
    people_per_org_pages: int = 2,
    per_page_people: int = 25,
) -> List[Dict[str, Any]]:
    """Org keyword search, then people at those orgs."""
    from venue_rental_config import (
        VENUE_RENTAL_ORG_EMPLOYEE_RANGES,
        VENUE_RENTAL_ORG_KEYWORD_TAGS,
        VENUE_RENTAL_ORG_LOCATIONS,
        VENUE_RENTAL_PERSON_SENIORITIES,
        VENUE_RENTAL_PERSON_TITLES,
    )

    tags = org_keyword_tags or VENUE_RENTAL_ORG_KEYWORD_TAGS
    locs = org_locations or VENUE_RENTAL_ORG_LOCATIONS
    titles = person_titles or VENUE_RENTAL_PERSON_TITLES
    seniorities = person_seniorities or VENUE_RENTAL_PERSON_SENIORITIES
    ranges = employee_ranges or VENUE_RENTAL_ORG_EMPLOYEE_RANGES
    people: List[Dict[str, Any]] = []
    org_ids = list(
        apollo.iter_organization_ids(
            org_keyword_tags=tags,
            organization_locations=locs,
            employee_ranges=ranges,
            max_pages=max_org_pages,
            per_page=100,
            revenue_min=revenue_min,
        )
    )
    for oid in org_ids:
        for page in range(1, people_per_org_pages + 1):
            def _call(org_id=oid, p=page):
                return apollo.search_people_by_orgs(
                    organization_ids=[org_id],
                    person_titles=titles,
                    person_seniorities=seniorities,
                    page=p,
                    per_page=per_page_people,
                    person_locations=person_locations,
                    require_verified_email=True,
                    include_similar_titles=include_similar_titles,
                )

            data = with_retry(_call, label=f"people_at_org {oid} p{page}", max_attempts=3)
            batch = _people_from_response(data)
            if not batch:
                break
            people.extend(batch)
    return dedupe_people_by_id(people)
