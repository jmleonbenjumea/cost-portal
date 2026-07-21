"""Formato europeo (es-ES) y parseo del feed de tipos de cambio del BCE."""
from datetime import date, datetime

import pytest

from app import fx
from app.formatting import fecha_es, format_number_es, mes_es


class TestFormatNumberEs:
    @pytest.mark.parametrize(
        ("value", "decimals", "expected"),
        [
            (1234.5, 2, "1.234,50"),
            (1234567.891, 2, "1.234.567,89"),
            (0.123456, 6, "0,123456"),
            (0, 2, "0,00"),
            (42, 0, "42"),
            (1000, 0, "1.000"),
            (-1234.5, 2, "-1.234,50"),
        ],
    )
    def test_separadores_intercambiados(self, value, decimals, expected):
        assert format_number_es(value, decimals) == expected

    def test_none_es_guion(self):
        assert format_number_es(None) == "—"


class TestFechas:
    def test_mes_en_espanol(self):
        assert mes_es(date(2026, 7, 1)) == "julio 2026"
        assert mes_es(datetime(2026, 1, 15)) == "enero 2026"

    def test_fecha_iso_a_europea(self):
        assert fecha_es("2026-07-21") == "21/07/2026"
        assert fecha_es("2026-07-21", con_anio=False) == "21/07"

    def test_fecha_vacia_o_ilegible(self):
        assert fecha_es(None) == "—"
        assert fecha_es("no-es-fecha") == "no-es-fecha"


_ECB_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time="2026-07-21">
      <Cube currency="USD" rate="1.2500"/>
      <Cube currency="GBP" rate="0.8600"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""


class TestParseoBce:
    def test_invierte_el_tipo_del_feed(self):
        # El BCE publica EUR→USD; el panel necesita USD→EUR.
        rate = fx.parse_ecb_xml(_ECB_XML)
        assert rate.usd_to_eur == pytest.approx(0.8)
        assert rate.rate_date == "2026-07-21"
        assert rate.is_official

    @pytest.mark.parametrize(
        "payload",
        [
            b'<Envelope xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref"/>',
            _ECB_XML.replace(b'currency="USD"', b'currency="JPY"'),
            _ECB_XML.replace(b'rate="1.2500"', b'rate="0"'),
        ],
        ids=["sin_cubo", "sin_usd", "tipo_cero"],
    )
    def test_feed_invalido_lanza(self, payload):
        with pytest.raises(ValueError):
            fx.parse_ecb_xml(payload)


class TestTipoVigente:
    def test_sin_cache_usa_el_valor_de_respaldo(self):
        fx._reset_for_tests()
        vigente = fx.current()
        assert not vigente.is_official
        assert vigente.usd_to_eur > 0
