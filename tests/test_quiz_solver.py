from quiz_solver import solve_question


def test_compound_growth_question_matches_example():
    question = "An investment of $31,500.00 grows at 12% compounded annually. What is its value after 7 years?"
    options = [
        "$62,175.41",
        "$57,960.00",
        "$69,636.46",
        "$26,460.00",
    ]

    assert solve_question(question, options) == "C"


def test_discount_question_uses_downward_percentage():
    question = "A jacket is marked down 15% from $320.00. What is the sale price?"
    options = [
        "$12.00",
        "$272.00",
        "$365.00",
        "$304.00",
    ]

    assert solve_question(question, options) == "B"


def test_percent_of_question_solves_basic_business_math():
    question = "What is 8% of $250.00?"
    options = [
        "$8.00",
        "$20.00",
        "$25.00",
        "$32.00",
    ]

    assert solve_question(question, options) == "B"
