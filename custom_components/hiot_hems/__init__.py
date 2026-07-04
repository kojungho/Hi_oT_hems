import logging
from datetime import timedelta
import requests
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .const import (
    DOMAIN, LOGIN_URL, ENERGY_URL, CLIENT_ID, 
    CONF_USERNAME, CONF_PASSWORD, CONF_SCAN_INTERVAL, 
    CONF_RETRY_INTERVAL, DEFAULT_RETRY_INTERVAL
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """UI 엔트리가 등록되면 세션 및 데이터를 완전히 동기화한 후 플랫폼을 로드합니다."""
    config = entry.data
    username = config.get(CONF_USERNAME)
    password = config.get(CONF_PASSWORD)
    scan_interval_minutes = config.get(CONF_SCAN_INTERVAL, 60)
    retry_interval_minutes = config.get(CONF_RETRY_INTERVAL, DEFAULT_RETRY_INTERVAL)

    base_headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "x-hiot-clientId": CLIENT_ID,
        "clientKey": CLIENT_ID,
        "User-Agent": "okhttp/4.10.0"
    }

    coordinator = HiothHemsCoordinator(hass, username, password, base_headers, scan_interval_minutes, retry_interval_minutes)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # 동적 주기 변경 옵션 감지를 위한 업데이터 리스너 등록
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """사용자가 주기를 변경하면 기기를 일시 정지 후 새로운 주기로 즉시 재시작합니다."""
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """통합구성요소 제거 시 엔트리를 해제합니다."""
    unload_ok = await hass.config_entries.async_forward_entry_unload(entry, "sensor")
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


class HiothHemsCoordinator(DataUpdateCoordinator):
    """매 시간 세션을 완벽히 초기화하여 실시간 검침 데이터를 보장하는 코디네이터"""
    def __init__(self, hass, username, password, headers, interval_minutes, retry_interval_minutes):
        self.normal_interval = timedelta(minutes=interval_minutes)
        self.retry_interval = timedelta(minutes=retry_interval_minutes)
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=self.normal_interval)
        self.username = username
        self.password = password
        self.headers = headers
        self.session = requests.Session()
        self.login_info = {}
        self.last_update_success = False

    def _fetch_data_from_api(self):
        self.session.cookies.clear()
        
        login_payload = {
            "condition": {
                "mobiledeviceostype": "android",
                "passwordvalu": self.password,
                "pushregistrationtoken": "fIpI7cbgQoq-B-ZCMUjaF9:APA91bEYndopdTmDx9Is4qLYQ7o2Q6OvqCyH4yBQfsSJPOnBPrYwcGjs4mQ7BNUIjH_U_avEhSJjVOQMxpymHYEAgsby96q5f63cnRdCSnuURDyuaJwwolo",
                "userid": self.username
            }
        }
        
        self.session.headers.update(self.headers)
        
        login_res = self.session.post(LOGIN_URL, json=login_payload, timeout=30)
        login_data = login_res.json()
        
        if login_res.status_code != 200 or "login" not in login_data or len(login_data["login"]) == 0:
            raise Exception("하이오티 상시 동기화를 위한 백엔드 로그인 세션 갱신 실패")
            
        self.login_info = login_data["login"][0]
        
        complex_cd = self.login_info.get("complexcd", "HDCGGPJ1")
        building_no = self.login_info.get("buildingno", "910")
        household_no = self.login_info.get("householdno", "1001")

        energy_payload = {
            "complexcd": complex_cd,
            "buildingno": building_no,
            "householdno": household_no
        }
        
        energy_res = self.session.post(ENERGY_URL, json=energy_payload, timeout=30)
        res_json = energy_res.json()
        
        return res_json

    def _is_data_valid(self, data):
        """서버 반환값이 실제로 유효한지 검증합니다."""
        if not data or not isinstance(data, dict): 
            return False
        energy = data.get("energyusage")
        if not energy or not isinstance(energy, list) or len(energy) == 0:
            return False
        # 전기 사용량 키가 존재하는지 확인하여 완전한 데이터인지 판별
        if "electricityusagevalu" not in energy[0] or energy[0]["electricityusagevalu"] is None:
            return False
        return True

    async def _async_update_data(self):
        try:
            res_json = await self.hass.async_add_executor_job(self._fetch_data_from_api)
            
            # 동적 간격 조정 로직 적용
            if self._is_data_valid(res_json):
                if self.update_interval != self.normal_interval:
                    _LOGGER.info("정상 데이터를 수신하여 기본 갱신 주기로 복귀합니다.")
                    self.update_interval = self.normal_interval
            else:
                if self.update_interval != self.retry_interval:
                    _LOGGER.warning("서버 데이터가 누락되어 재조회 주기(%s분)로 전환합니다.", self.retry_interval.total_seconds() / 60)
                    self.update_interval = self.retry_interval
                    
            return res_json
            
        except Exception as err:
            # 통신/파싱 에러 시에도 재조회 주기로 변경
            if self.update_interval != self.retry_interval:
                self.update_interval = self.retry_interval
            raise UpdateFailed(f"하이오티 데이터 폴링 에러: {err}")
