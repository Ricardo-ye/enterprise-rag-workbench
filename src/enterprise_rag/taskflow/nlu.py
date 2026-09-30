import re
from typing import Any


class SlotExtractor:
    _phone = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
    _vin = re.compile(r"(?<![A-Z0-9])[A-HJ-NPR-Z0-9]{17}(?![A-Z0-9])", re.IGNORECASE)
    _work_order = re.compile(r"(?:工单|单号)[:：#\s]*([A-Z0-9-]{4,})", re.IGNORECASE)
    _policy = re.compile(r"(?:保单|保单号)[:：#\s]*([A-Z0-9-]{4,})", re.IGNORECASE)
    _fleet_size = re.compile(r"(\d{1,6})\s*辆")
    _service_center = re.compile(r"([\u3400-\u9fffA-Za-z0-9]{2,20}(?:服务中心|门店))")
    _time = re.compile(
        r"(今天|明天|后天|本周[一二三四五六日天]|下周[一二三四五六日天]|"
        r"\d{1,2}月\d{1,2}日)(?:\s*(上午|下午|晚上|\d{1,2}(?::\d{2})?点?))?"
    )

    def extract(
        self,
        query: str,
        required_slots: list[str],
        provided_slots: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        slots = {
            key: value
            for key, value in (provided_slots or {}).items()
            if key in required_slots and value not in (None, "")
        }
        extractors = {
            "contact": self._extract_phone,
            "vehicle_id": self._extract_vehicle_id,
            "preferred_time": self._extract_time,
            "incident_time": self._extract_time,
            "service_type": self._extract_service_type,
            "service_center": self._extract_service_center,
            "work_order_id": self._extract_work_order,
            "policy_number": self._extract_policy,
            "claim_type": self._extract_claim_type,
            "model": self._extract_model,
            "city": self._extract_city,
            "location": self._extract_city,
            "company_name": self._extract_company,
            "fleet_size": self._extract_fleet_size,
        }
        for slot in required_slots:
            if slot in slots or slot not in extractors:
                continue
            value = extractors[slot](query)
            if value is not None:
                slots[slot] = value
        return slots

    def _extract_phone(self, query: str) -> str | None:
        match = self._phone.search(query)
        return match.group(0) if match else None

    def _extract_vehicle_id(self, query: str) -> str | None:
        match = self._vin.search(query)
        return match.group(0).upper() if match else None

    def _extract_time(self, query: str) -> str | None:
        match = self._time.search(query)
        return "".join(part for part in match.groups() if part) if match else None

    def _extract_service_type(self, query: str) -> str | None:
        if "保养" in query:
            return "保养"
        if "维修" in query or "修车" in query:
            return "维修"
        return None

    def _extract_service_center(self, query: str) -> str | None:
        match = self._service_center.search(query)
        return match.group(1) if match else None

    def _extract_work_order(self, query: str) -> str | None:
        match = self._work_order.search(query)
        return match.group(1).upper() if match else None

    def _extract_policy(self, query: str) -> str | None:
        match = self._policy.search(query)
        return match.group(1).upper() if match else None

    def _extract_claim_type(self, query: str) -> str | None:
        for claim_type in ("车辆损失", "人伤", "玻璃", "涉水", "盗抢"):
            if claim_type in query:
                return claim_type
        return None

    def _extract_model(self, query: str) -> str | None:
        match = re.search(r"(?:试驾|车型)[:：\s]*([A-Za-z0-9\u3400-\u9fff-]{2,20})", query)
        return match.group(1) if match else None

    def _extract_city(self, query: str) -> str | None:
        for city in ("北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京"):
            if city in query:
                return city
        return None

    def _extract_company(self, query: str) -> str | None:
        match = re.search(r"([\u3400-\u9fffA-Za-z0-9]{2,30}(?:公司|集团))", query)
        return match.group(1) if match else None

    def _extract_fleet_size(self, query: str) -> int | None:
        match = self._fleet_size.search(query)
        return int(match.group(1)) if match else None
