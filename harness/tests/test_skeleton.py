def test_package_importable():
    import harness
    import harness.tools
    assert harness.__name__ == "harness"