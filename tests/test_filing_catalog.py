"""Ids solo del catálogo, remitente limpio y sensibilidad en el vocabulario de la TRD (spec Recepción nueva §3)."""
from app.utils.filing_catalog import catalog_prompt_block, empty_suggestion, normalize_sensitivity_level, validate_suggestion

CATALOGO = {
    "filing_type": "ENT",
    "dependencies": [{"id": 100, "name": "Despacho"}, {"id": 200, "name": "Hacienda"}],
    "typologies": [
        {"id": 40, "name": "Petición", "code": "01", "series": "Peticiones", "subseries": None, "dependence_ids": [100]},
        {"id": 41, "name": "Recurso de reposición", "code": "02", "series": "Recursos", "subseries": "Reposición", "dependence_ids": [200]},
    ],
}


def test_el_bloque_del_prompt_lista_ids_nombres_y_el_rol_de_la_dependencia():
    bloque = catalog_prompt_block(CATALOGO)
    assert "CATÁLOGO DE LA ENTIDAD" in bloque
    assert "- [100] Despacho" in bloque
    assert "Recursos › Reposición:\n  - [41] Recurso de reposición (código 02) — dependencias: 200" in bloque
    assert "Peticiones:\n  - [40] Petición (código 01) — dependencias: 100" in bloque
    assert "recibir y tramitar" in bloque


def test_el_bloque_limpia_textos_y_agrupa_por_serie_y_subserie():
    catalogo = {
        "filing_type": "ENT",
        "dependencies": [{"id": 1, "name": "Despacho\ndel   Alcalde"}],
        "typologies": [
            {"id": 5, "name": "Oficio\nexterno", "code": None, "series": "Comunicaciones", "subseries": None, "dependence_ids": []},
            {"id": 6, "name": "Circular", "code": "07", "series": "Comunicaciones", "subseries": None, "dependence_ids": [1]},
            {"id": 7, "name": "Suelta", "code": None, "series": None, "subseries": None, "dependence_ids": []},
        ],
    }
    bloque = catalog_prompt_block(catalogo)
    assert "- [1] Despacho del Alcalde" in bloque
    assert bloque.count("Comunicaciones:") == 1
    assert "Comunicaciones:\n  - [5] Oficio externo\n  - [6] Circular (código 07) — dependencias: 1" in bloque
    assert "Sin serie:\n  - [7] Suelta" in bloque
    assert "\n\n" not in bloque


def test_sin_catalogo_no_hay_bloque():
    assert catalog_prompt_block(None) == ""
    assert catalog_prompt_block({"dependencies": [], "typologies": []}) == ""


def test_ids_como_texto_ajenos_y_dependencia_no_duena():
    assert validate_suggestion({"typology_id": "40", "typology_confidence": 0.9, "dependence_id": "100", "dependence_confidence": 0.8}, CATALOGO)["typology_id"] == 40

    ajeno = validate_suggestion({"typology_id": 999, "typology_confidence": 0.95, "dependence_id": 555, "dependence_confidence": 0.9}, CATALOGO)
    assert (ajeno["typology_id"], ajeno["typology_confidence"], ajeno["dependence_id"], ajeno["dependence_confidence"]) == (None, 0.0, None, 0.0)

    corregida = validate_suggestion({"typology_id": 41, "typology_confidence": 0.9, "dependence_id": 100, "dependence_confidence": 0.7}, CATALOGO)
    assert (corregida["dependence_id"], corregida["dependence_confidence"]) == (200, 0.9)


def test_tipologia_valida_sin_dependencia_toma_la_duena_unica():
    sugerencia = validate_suggestion({"typology_id": 40, "typology_confidence": 0.82}, CATALOGO)
    assert (sugerencia["dependence_id"], sugerencia["dependence_confidence"]) == (100, 0.82)


def test_sin_catalogo_se_descartan_los_ids_pero_se_conserva_el_remitente():
    sugerencia = validate_suggestion({"typology_id": 40, "typology_confidence": 0.9, "sender": {"name": "Ana Pérez"}, "sender_confidence": 0.7}, None)
    assert (sugerencia["typology_id"], sugerencia["dependence_id"]) == (None, None)
    assert (sugerencia["sender"]["name"], sugerencia["sender_confidence"]) == ("Ana Pérez", 0.7)


def test_remitente_limpio_tipo_valido_y_confianza_acotada():
    sugerencia = validate_suggestion({"sender": {"name": "  Constructora Andina S.A.S. ", "kind": "Jurídica", "identification": "", "email": "contacto@andina.co"}, "sender_confidence": 7}, CATALOGO)
    assert sugerencia["sender"] == {"name": "Constructora Andina S.A.S.", "kind": None, "identification": None, "phone": None, "address": None, "email": "contacto@andina.co"}
    assert sugerencia["sender_confidence"] == 1.0
    assert validate_suggestion({"sender": {"name": "Ana", "kind": "natural"}}, None)["sender"]["kind"] == "natural"
    assert validate_suggestion({"sender": {"name": None}, "sender_confidence": 0.9}, None)["sender_confidence"] == 0.0


def test_la_confianza_del_remitente_se_conserva_si_solo_hay_identificacion():
    sugerencia = validate_suggestion({"sender": {"name": None, "identification": "900123456"}, "sender_confidence": 0.8}, None)
    assert sugerencia["sender"]["identification"] == "900123456"
    assert sugerencia["sender_confidence"] == 0.8


def test_sugerencia_vacia_con_la_forma_del_contrato():
    assert empty_suggestion() == {
        "typology_id": None, "typology_confidence": 0.0, "dependence_id": None, "dependence_confidence": 0.0,
        "sender": {"name": None, "kind": None, "identification": None, "phone": None, "address": None, "email": None},
        "sender_confidence": 0.0,
    }


def test_sensibilidad_en_vocabulario_trd():
    assert [normalize_sensitivity_level(v) for v in ["publico", "Reservado", "público", "CONFIDENCIAL ", "public", "internal", "confidential", "restricted", "no_evaluado", "raro", None]] == [
        "publico", "reservado", "publico", "confidencial", "publico", "clasificado", "confidencial", "reservado", "no_evaluado", "clasificado", "clasificado",
    ]
