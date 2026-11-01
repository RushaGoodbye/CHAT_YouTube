from rg_youtube_control.free_tools import _seo_editorial_preview_flags


def test_catches_generic_srt_preview_even_when_format_fully_populated():
    title = "війна проти України: про що говорять у чат-рулетці?"
    alternatives = [
        "робота та зайнятість: що кажуть співрозмовники?",
        "здоров'я та медицина: які запитання виникають?",
        "зарплати та доходи: думки учасників розмови",
    ]
    desc = (
        "У цьому випуску чат-рулетки росіяни обговорюють війна проти України, "
        "робота та зайнятість, здоров'я та медицина. "
        "Співрозмовники висловлюють різні версії, особисті оцінки та "
        "пояснюють, як вони бачать причини й наслідки подій. "
        "Дивіться повну розмову та оцініть аргументи співрозмовників самі."
    )
    flags = _seo_editorial_preview_flags(title, desc, alternatives)
    assert "GENERIC_PRIMARY_TITLE" in flags
    assert "GENERIC_AB_VARIANTS" in flags
    assert "TEMPLATE_DESCRIPTION" in flags
    assert "UNGRAMMATICAL_DESCRIPTION" in flags


def test_does_not_flag_specific_editorial_proposal():
    title = "ЗВІЛЬНЕННЯ ШОЙГУ: КОРУПЦІЯ ЧИ «ВСЕ ЗА ПЛАНОМ»?"
    alternatives = [
        "Що росіяни кажуть про рішення усунути Шойгу з Міноборони РФ?",
        "Чому частина співрозмовників згадує корупцію після зміни Шойгу?",
        "«Все за планом»? Реакція росіян на кадрові зміни в Міноборони РФ",
    ]
    desc = (
        "У розмові порушують тему переведення Шойгу з посади міністра "
        "оборони Росії. Деякі співрозмовники припускають корупційні мотиви, "
        "інші повторюють формулу «все за планом». "
        "Учасники розмови згадують Бєлоусова й обговорюють кадрове рішення."
    )
    assert _seo_editorial_preview_flags(title, desc, alternatives) == []


def test_allows_narrow_source_topic_without_fake_event():
    assert _seo_editorial_preview_flags(
        "Шойгу: реакція російських співрозмовників на зміну посади",
        "Співрозмовники згадують переведення Шойгу на іншу посаду "
        "та сперечаються про наслідки кадрового рішення.",
        [
            "Шойгу після Міноборони РФ: як це пояснюють росіяни?",
            "Згадки про Бєлоусова у розмові про зміну посади Шойгу",
            "Що росіяни думають про кадрові рішення у керівництві РФ?",
        ],
    ) == []


def test_flags_repeated_sentences_and_duplicate_tags_even_if_format_valid():
    description = (
        "У розмові росіяни сперечаються про рішення влади і причини війни. "
        "Ведучий запитує, як співрозмовники пояснюють власну позицію. "
        "У розмові росіяни сперечаються про рішення влади і причини війни."
    )
    flags = _seo_editorial_preview_flags(
        "Росіяни про рішення влади",
        description,
        ["Питання до влади", "Розмова про війну", "Причини вибору президента"],
        ["Росія", "чат рулетка", "Росія"],
    )
    assert "DUPLICATED_TAGS" in flags
    assert "REPEATED_DESCRIPTION_SENTENCES" in flags


def test_flags_near_identical_ab_and_mixed_language():
    flags = _seo_editorial_preview_flags(
        "Коллективна відповідальність за війну",
        "Розмова про відповідальність громадян за державні рішення та війну.",
        [
            "Шойгу звільнили через корупцію?",
            "Шойгу звільнили через корупцію!",
            "Чому змінили Шойгу?",
        ],
        ["війна", "Раша Гудбай"],
    )
    assert "SIMILAR_AB_ANGLES" in flags
    assert "MIXED_LANGUAGE_WORDS" in flags


def test_unattributed_occupation_framing_gets_editorial_warning():
    flags = _seo_editorial_preview_flags(
        "Луганськ після входу до РФ: зміни і санкції",
        "У відео обговорюється ситуація та слова місцевого співрозмовника.",
        ["Луганськ і окупація", "Санкції проти РФ", "Розмова про Луганськ"],
    )
    assert "OCCUPATION_FRAMING_REVIEW" in flags


def test_russian_dialog_word_is_detected_in_ukrainian_ab():
    flags = _seo_editorial_preview_flags(
        "Луганськ: дискусія про зміни",
        "Співрозмовники розмовляють про події та наслідки для мешканців.",
        ["Диалог про Луганськ", "Мешканці і зміни", "Про що розповідають жителі"],
    )
    assert "RUSSIAN_WORD_DIALOG" in flags


def test_generic_one_word_tags_are_not_editorial_pass():
    flags = _seo_editorial_preview_flags(
        "Саратов: питання про місцеві події",
        "Співрозмовник обговорює стан міста і відповідає на запитання.",
        ["Що сталося в Саратові?", "Саратов і місцева влада", "Діалог про Саратов"],
        ["Росія", "Саратов", "Озон", "інтерв'ю", "думки",
         "чат рулетка", "події Саратова", "російські співрозмовники"],
    )
    assert "GENERIC_ONE_WORD_TAGS" in flags
