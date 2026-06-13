"""Translation file reloaders are no-ops in the extracted ORM."""


def watch_for_translation_changes(sender, **kwargs):
    pass


def translation_file_changed(sender, file_path, **kwargs):
    return False
