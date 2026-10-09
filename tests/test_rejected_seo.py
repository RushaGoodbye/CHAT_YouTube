from rg_youtube_control.rejected_seo import package_fingerprint, rejected_package_key


def test_rejected_identical_package_same_fingerprint():
    a = package_fingerprint("Назва", "Опис", ["Росія", "Україна"])
    b = package_fingerprint("Назва", "Опис", ["україна", "росія"])
    assert a == b


def test_reworked_content_changes_fingerprint():
    previous = package_fingerprint("Стара назва", "Опис", ["чат рулетка"])
    changed = package_fingerprint("Нова назва", "Опис", ["чат рулетка"])
    assert previous != changed


def test_rejection_key_scoped_to_video():
    assert rejected_package_key("videoA") != rejected_package_key("videoB")
