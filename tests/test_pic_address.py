from pmkt_alert.prompts import style_text
from pmkt_alert.store import Store


def test_default_style_has_no_pic_address(tmp_path):
    assert Store(tmp_path).get_style()["pic_address"] == {}


def test_set_pic_address_persists_per_pic(tmp_path):
    s = Store(tmp_path)
    s.set_pic_address("PIC A", {"self": "em", "call": "chị", "name": "Tâm"})
    s.set_pic_address("PIC B", {"self": "mình", "call": "name", "name": "Khang"})
    assert s.get_style()["pic_address"]["PIC A"] == {"self": "em", "call": "chị", "name": "Tâm"}
    assert set(s.get_style()["pic_address"]) == {"PIC A", "PIC B"}


def test_style_text_uses_pic_address():
    style = {"language": "vi_en_terms", "pronoun": "em_anhchi", "length": "short", "tone": "friendly_direct",
             "emoji": "low", "samples": [], "rules": "",
             "pic_address": {"PIC A": {"self": "em", "call": "chị", "name": "Tâm"},
                             "PIC B": {"self": "mình", "call": "name", "name": "Khang"}}}
    a = style_text(style, "PIC A")
    assert 'tự xưng "em"' in a and 'gọi PIC là "chị Tâm"' in a
    b = style_text(style, "PIC B")
    assert 'tự xưng "mình"' in b and 'chỉ gọi tên "Khang"' in b and "không dùng anh/chị" in b
    assert "tự xưng" not in style_text(style, "PIC C")  # falls back to the general pronoun setting


def test_style_prompt_is_a_short_message_without_refs():
    from pmkt_alert.prompts import style_prompt
    style = {"language": "vi_en_terms", "pronoun": "em_anhchi", "length": "short", "tone": "friendly_direct",
             "emoji": "low", "samples": [], "rules": "", "pic_address": {}}
    p = style_prompt(style, {"pic": "PIC A"}, {"pl": [], "camp": []})
    assert "refs" not in p and "unit_id" not in p.split("Dữ liệu:")[0].replace("không ghi unit_id", "")
    assert "không ghi unit_id" in p and "tối đa 10 dòng" in p
