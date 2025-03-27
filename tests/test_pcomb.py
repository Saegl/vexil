from pcomb import Source, char, keyword, ws1, choice


def test_char() -> None:
    a_parser = char("a")
    source = Source("alisher")
    out = a_parser(source).unwrap()
    assert out == "a"
    assert source.pos == 1

    source = Source("saegl")
    fail = a_parser(source)
    assert not fail.is_succ()
    assert source.pos == 0


def test_keyword() -> None:
    def_parser = keyword("def")
    source = Source("def")
    out = def_parser(source).unwrap()
    assert out == "def"
    assert source.pos == 3

    out2 = def_parser(source)
    assert not out2.is_succ()


def test_two_keywords() -> None:
    s = Source("def main")

    def_parser = keyword("def")
    main_parser = keyword("main")

    assert def_parser(s).is_succ()
    assert ws1(s).is_succ()
    assert main_parser(s).is_succ()


def test_choice() -> None:
    function_keyword = keyword("function")
    class_keyword = keyword("class")
    stmt = choice(function_keyword, class_keyword)

    s = Source("class")
    out = stmt(s)
    assert out.is_succ()

    s = Source("function")
    out = stmt(s)
    assert out.is_succ()

    s = Source("module")
    out = stmt(s)
    assert not out.is_succ()
