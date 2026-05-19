from wagtail import blocks


class LyricsLineBlock(blocks.StructBlock):
    """單行歌詞，左右欄對應。"""

    left = blocks.TextBlock(
        required=False,
        label="左欄",
        rows=2,
        help_text="這一行的中文／主唱。可留空（讓對方獨唱）。",
    )
    right = blocks.TextBlock(
        required=False,
        label="右欄",
        rows=2,
        help_text="這一行的英文／合音。可留空。",
    )

    class Meta:
        icon = "doc-full"
        label = "歌詞行"


class LyricsSectionBlock(blocks.StructBlock):
    """歌詞段落（主歌／副歌／Bridge 等）。"""

    section_name = blocks.CharBlock(
        required=False,
        label="段落名稱",
        help_text="例：Verse 1、Chorus、Bridge、Outro",
    )
    section_name_alt = blocks.CharBlock(
        required=False,
        label="段落名稱（右欄）",
        help_text="若雙語想要兩種寫法，例：左『主歌』右『Verse』。留空則沿用左欄。",
    )
    lines = blocks.ListBlock(
        LyricsLineBlock(),
        label="歌詞行",
        min_num=1,
    )

    class Meta:
        icon = "list-ul"
        label = "段落"


class LyricsStreamBlock(blocks.StreamBlock):
    """LyricsPage 的 body 欄位接受的 block 類型。"""

    section = LyricsSectionBlock()
    note = blocks.RichTextBlock(
        features=["bold", "italic", "link"],
        label="註解 / 備註",
        help_text="不屬於歌詞主體的補充文字，例：原作者註、翻譯者說明。",
        required=False,
    )