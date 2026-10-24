def test_lower_name_keeps_acronyms() -> None:
    from alfa_insight.text.normalize import lower_name

    assert lower_name("Ключевая ставка ЦБ") == "ключевая ставка ЦБ"
    assert lower_name("Опт: металлы и руды") == "опт: металлы и руды"
    assert lower_name("Санкции США и ВЭД") == "санкции США и ВЭД"
    assert lower_name(None) == ""
