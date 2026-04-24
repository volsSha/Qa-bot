from qa_bot.models import FormInfo, HeadingInfo, ImageInfo, LinkInfo, PreprocessedPage
from qa_bot.preprocessor import preprocess


def test_happy_path_well_formed_html():
    html = """
    <html>
        <head>
            <title>My Page</title>
            <meta name="description" content="A test page">
            <meta property="og:type" content="website">
        </head>
        <body>
            <h1>Main Title</h1>
            <p>Hello world</p>
            <img src="/logo.png" alt="Logo">
            <img src="/banner.jpg">
            <a href="/about">About Us</a>
            <p>Some   extra   spaces</p>
            <h2>Subtitle</h2>
        </body>
    </html>
    """

    result = preprocess(html)

    assert result.title == "My Page"
    assert "Hello world" in result.text_content
    assert "Some extra spaces" in result.text_content
    assert result.images == [
        ImageInfo(src="/logo.png", alt="Logo"),
        ImageInfo(src="/banner.jpg", alt=None),
    ]
    assert result.links == [LinkInfo(href="/about", text="About Us")]
    assert result.headings == [
        HeadingInfo(level=1, text="Main Title"),
        HeadingInfo(level=2, text="Subtitle"),
    ]
    assert result.meta_tags == {
        "description": "A test page",
        "og:type": "website",
    }


def test_empty_html_string():
    result = preprocess("")

    assert result == PreprocessedPage(
        title=None,
        text_content="",
        images=[],
        links=[],
        forms=[],
        meta_tags={},
        headings=[],
    )


def test_whitespace_only_html():
    result = preprocess("   \n\t  ")

    assert result == PreprocessedPage(
        title=None,
        text_content="",
        images=[],
        links=[],
        forms=[],
        meta_tags={},
        headings=[],
    )


def test_html_with_only_scripts_and_styles():
    html = """
    <html>
        <head><title>Hidden</title></head>
        <body>
            <script>var x = 1;</script>
            <style>body { color: red; }</style>
            <noscript>Enable JS</noscript>
            <!-- a comment -->
        </body>
    </html>
    """

    result = preprocess(html)

    assert result.title == "Hidden"
    assert result.text_content == ""
    assert "var x" not in result.text_content
    assert "color: red" not in result.text_content


def test_malformed_html_handled_gracefully():
    html = "<div><p>unclosed<b>bold</div>"

    result = preprocess(html)

    assert isinstance(result, PreprocessedPage)
    assert "unclosed" in result.text_content
    assert "bold" in result.text_content


def test_unicode_characters_preserved():
    html = """
    <html>
        <head><title>日本語ページ</title></head>
        <body>
            <p>Héllo wörld — café résumé</p>
            <p>你好世界 🌍</p>
        </body>
    </html>
    """

    result = preprocess(html)

    assert result.title == "日本語ページ"
    assert "Héllo wörld" in result.text_content
    assert "你好世界" in result.text_content


def test_forms_count_inputs_and_detect_labels():
    html = """
    <html><body>
        <form id="login">
            <label for="email">Email</label>
            <input type="email" id="email">
            <input type="password" id="pass">
            <label for="pass">Password</label>
            <textarea id="bio"></textarea>
            <select id="country"><option>US</option></select>
        </form>
        <form id="search">
            <label><input type="text" name="q"></label>
            <input type="submit" value="Go">
        </form>
    </body></html>
    """

    result = preprocess(html)

    assert len(result.forms) == 2
    assert result.forms[0] == FormInfo(inputs_count=4, has_labels=True)
    assert result.forms[1] == FormInfo(inputs_count=2, has_labels=True)


def test_forms_no_labels():
    html = """
    <html><body>
        <form>
            <input type="text">
            <input type="submit">
        </form>
    </body></html>
    """

    result = preprocess(html)

    assert result.forms == [FormInfo(inputs_count=2, has_labels=False)]


def test_meta_tags_name_and_property():
    html = """
    <html><head>
        <meta name="author" content="John">
        <meta name="viewport" content="width=device-width">
        <meta property="og:title" content="My Page">
        <meta property="og:description" content="Test">
        <meta charset="utf-8">
    </head><body></body></html>
    """

    result = preprocess(html)

    assert result.meta_tags["author"] == "John"
    assert result.meta_tags["viewport"] == "width=device-width"
    assert result.meta_tags["og:title"] == "My Page"
    assert result.meta_tags["og:description"] == "Test"
    assert "charset" not in result.meta_tags


def test_nav_footer_header_removed():
    html = """
    <html><head><title>Test</title></head>
    <body>
        <header>Site Header</header>
        <nav>Home About Contact</nav>
        <main>
            <h1>Real Content</h1>
            <p>Visible paragraph</p>
        </main>
        <footer>Site Footer</footer>
    </body></html>
    """

    result = preprocess(html)

    assert "Site Header" not in result.text_content
    assert "Home About Contact" not in result.text_content
    assert "Site Footer" not in result.text_content
    assert "Real Content" in result.text_content
    assert "Visible paragraph" in result.text_content


def test_iframe_removed():
    html = """
    <html><body>
        <iframe src="https://example.com/embed"></iframe>
        <p>Content outside iframe</p>
    </body></html>
    """

    result = preprocess(html)

    assert "Content outside iframe" in result.text_content


def test_html_comments_removed():
    html = """
    <html><body>
        <!-- This is a comment -->
        <p>Visible text</p>
        <!-- Another comment -->
    </body></html>
    """

    result = preprocess(html)

    assert "comment" not in result.text_content.lower()
    assert "Visible text" in result.text_content
