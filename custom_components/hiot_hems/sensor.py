import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.util import dt as dt_util
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

ENERGY_TYPES = {
    "electricity": {"key": "electricityusagevalu", "name": "전기", "unit": "kWh", "class": SensorDeviceClass.ENERGY},
    "gas": {"key": "gasusagevalu", "name": "가스", "unit": "m³", "class": SensorDeviceClass.GAS},
    "water": {"key": "waterusagevalu", "name": "수도", "unit": "m³", "class": SensorDeviceClass.WATER},
    "hot_water": {"key": "hotwaterusagevalu", "name": "온수", "unit": "m³", "class": SensorDeviceClass.WATER},
    "heating": {"key": "heatingusagevalu", "name": "난방", "unit": "m³", "class": SensorDeviceClass.GAS}
}

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    login_info = coordinator.login_info
    building_no = login_info.get("buildingno", "Unknown")
    household_no = login_info.get("householdno", "Unknown")
    complex_nm = login_info.get("complexnm", "힐스테이트 운정")
    
    device_info = DeviceInfo(
        identifiers={(DOMAIN, f"{login_info.get('complexcd', 'HL')}_{building_no}_{household_no}")},
        name=f"{complex_nm} {building_no} {household_no}호 월패드",
        manufacturer="Hyundai AutoEver",
        model="Hi-oT HEMS",
        sw_version="2.2.1"
    )

    entities = []
    for e_type, meta in ENERGY_TYPES.items():
        # 당월 누적 사용량만 TOTAL_INCREASING 부여
        entities.append(HiotHemsSensor(coordinator, device_info, meta["key"], f"{meta['name']} 사용량", meta["unit"], meta["class"], "current", SensorStateClass.TOTAL_INCREASING))
        # 나머지는 통계 연산용이므로 state_class를 None으로 설정 (경고 방지)
        entities.append(HiotHemsSensor(coordinator, device_info, meta["key"], f"{meta['name']} 동일평수 평균", meta["unit"], meta["class"], "mean", None))
        entities.append(HiotHemsSensor(coordinator, device_info, meta["key"], f"{meta['name']} 전년동월 사용량", meta["unit"], meta["class"], "previous", None))
        entities.append(HiotHemsComparisonSensor(coordinator, device_info, meta["key"], f"{meta['name']} 전년동월 대비", meta["unit"], meta["class"]))

    entities.append(HiotHemsLastUpdatedSensor(coordinator, device_info))
    async_add_entities(entities)

class HiotHemsLastUpdatedSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    def __init__(self, coordinator, device_info):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._attr_name = "힐스테이트 HEMS 최근 갱신 시간"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_unique_id = "hillstate_hems_last_updated_time"
        self._attr_device_info = device_info
    @property
    def native_value(self):
        return dt_util.as_utc(dt_util.now()) if self.coordinator.last_update_success else None

class HiotHemsSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, device_info, data_key, name, unit, device_class, data_type, state_class):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._data_key = data_key
        self._data_type = data_type
        self._sensor_name = name
        self._attr_name = f"힐스테이트 {name}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class # [수정] 위에서 넘겨받은 state_class 적용
        self._attr_unique_id = f"hillstate_hems_{data_type}_{data_key}"
        self._attr_device_info = device_info
        self._last_valid_value = None

    @property
    def native_value(self):
        data = self.coordinator.data
        if not data or not isinstance(data, dict): return self._last_valid_value
        target_group = data.get("energyusage") if self._data_type == "current" else \
                       data.get("meanenergyusage") if self._data_type == "mean" else data.get("previousenergyusage")
        if target_group and isinstance(target_group, list) and len(target_group) > 0:
            val = target_group[0].get(self._data_key)
            if val is not None:
                self._last_valid_value = float(val) if self._data_type == "current" else val
                return self._last_valid_value
        return self._last_valid_value

class HiotHemsComparisonSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, device_info, data_key, name, unit, device_class):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._data_key = data_key
        self._attr_name = f"힐스테이트 {name}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = None # [수정] 증감량은 통계 성격이 아니므로 None 처리
        self._attr_unique_id = f"hillstate_hems_compare_{data_key}"
        self._attr_device_info = device_info
        self._last_valid_value = None

    @property
    def native_value(self):
        data = self.coordinator.data
        if data and isinstance(data, dict):
            curr = data.get("energyusage")
            prev = data.get("previousenergyusage")
            if curr and prev and len(curr) > 0 and len(prev) > 0:
                try:
                    self._last_valid_value = round(float(curr[0].get(self._data_key, 0)) - float(prev[0].get(self._data_key, 0)), 2)
                    return self._last_valid_value
                except: pass
        return self._last_valid_value
