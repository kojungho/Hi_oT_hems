import logging
import asyncio
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .const import (
    DOMAIN, LOGIN_URL, CLIENT_ID, CONF_USERNAME, CONF_PASSWORD, 
    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL,
    CONF_RETRY_INTERVAL, DEFAULT_RETRY_INTERVAL
)

_LOGGER = logging.getLogger(__name__)

class HiotHemsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """하이오티 UI 설정 흐름을 제어합니다."""
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> 'HiotHemsOptionsFlowHandler':
        """기기 설정카드 진입 시 내부 500 에러 없이 핸들러를 바인딩합니다."""
        return HiotHemsOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        """통합구성요소 최초 추가 시 진입점입니다."""
        errors = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            success = await self._test_login(
                session, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            
            if success:
                final_input = {
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_SCAN_INTERVAL: user_input["갱신_주기_분단위"],
                    CONF_RETRY_INTERVAL: user_input["에러시_재조회_주기_분단위"]
                }
                return self.async_create_entry(
                    title=f"힐스테이트 HEMS ({user_input[CONF_USERNAME]})", 
                    data=final_input
                )
            else:
                errors["base"] = "invalid_auth"

        data_schema = vol.Schema({
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Optional("갱신_주기_분단위", default=DEFAULT_SCAN_INTERVAL): vol.All(vol.Coerce(int), vol.Range(min=5)),
            vol.Optional("에러시_재조회_주기_분단위", default=DEFAULT_RETRY_INTERVAL): vol.All(vol.Coerce(int), vol.Range(min=1)),
        })

        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    async def _test_login(self, session, username, password):
        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "x-hiot-clientId": CLIENT_ID,
            "clientKey": CLIENT_ID,
            "User-Agent": "okhttp/4.10.0"
        }
        payload = {
            "condition": {
                "mobiledeviceostype": "android",
                "passwordvalu": password,
                "pushregistrationtoken": "fIpI7cbgQoq-B-ZCMUjaF9:APA91bEYndopdTmDx9Is4qLYQ7o2Q6OvqCyH4yBQfsSJPOnBPrYwcGjs4mQ7BNUIjH_U_avEhSJjVOQMxpymHYEAgsby96q5f63cnRdCSnuURDyuaJwwolo",
                "userid": username
            }
        }
        try:
            async with asyncio.timeout(10):
                async with session.post(LOGIN_URL, headers=headers, json=payload) as response:
                    return response.status == 200
        except Exception:
            return False


class HiotHemsOptionsFlowHandler(config_entries.OptionsFlow):
    """동적 옵션 변경을 지원하는 특화 핸들러 클래스입니다."""
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """[교정 부] HA 코어 프레임워크 속성 셋 충돌을 우회하기 위해 변수 풀 격리 명명"""
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """동적 갱신 주기 폼을 호출하고 데이터를 리셋합니다."""
        if user_input is not None:
            # 변수 충돌 없는 갱신 명령 처리 완료
            self.hass.config_entries.async_update_entry(
                self._config_entry, 
                data={
                    **self._config_entry.data, 
                    CONF_SCAN_INTERVAL: user_input["갱신_주기_분단위"],
                    CONF_RETRY_INTERVAL: user_input["에러시_재조회_주기_분단위"]
                }
            )
            return self.async_create_entry(title="", data={})

        current_interval = self._config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        current_retry = self._config_entry.data.get(CONF_RETRY_INTERVAL, DEFAULT_RETRY_INTERVAL)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional("갱신_주기_분단위", default=current_interval): vol.All(vol.Coerce(int), vol.Range(min=5)),
                vol.Optional("에러시_재조회_주기_분단위", default=current_retry): vol.All(vol.Coerce(int), vol.Range(min=1)),
            })
        )
