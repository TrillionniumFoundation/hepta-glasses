from pathlib import Path

source = Path('services/skills/memory_service.py')
text = source.read_text(encoding='utf-8')
old = '_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\\Z")\n'
new = old + '_OPAQUE_IDENTIFIER = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.:-]{0,255}\\Z")\n'
if text.count(old) != 1:
    raise SystemExit('memory identifier declaration drift')
text = text.replace(old, new, 1)
old = '''    @staticmethod
    def _identifier(value: object, code: str = "memory_service_binding_invalid") -> str:
        if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
            raise MemoryServiceError(code)
        return value
'''
new = old + '''
    @staticmethod
    def _opaque_identifier(
        value: object, code: str = "memory_service_binding_invalid"
    ) -> str:
        if type(value) is not str or _OPAQUE_IDENTIFIER.fullmatch(value) is None:
            raise MemoryServiceError(code)
        return value
'''
if text.count(old) != 1:
    raise SystemExit('memory identifier method drift')
text = text.replace(old, new, 1)
old = '                memory_id=self._identifier(memory_id),\n'
new = '                memory_id=self._opaque_identifier(memory_id),\n'
if text.count(old) != 1:
    raise SystemExit('memory delete binding drift')
source.write_text(text.replace(old, new, 1), encoding='utf-8')

test = Path('services/skills/test_memory_service.py')
text = test.read_text(encoding='utf-8')
marker = '    def test_plaintext_and_bearer_are_not_persisted(self) -> None:\n'
method = '''    def test_urlsafe_memory_ids_may_start_with_urlsafe_punctuation(self) -> None:
        for memory_id in ("_legacy_urlsafe_id", "-legacy_urlsafe_id"):
            self.assertFalse(
                self.service.delete(
                    authorization=self.authorization,
                    memory_id=memory_id,
                )
            )

'''
if text.count(marker) != 1:
    raise SystemExit('memory test insertion drift')
if method not in text:
    text = text.replace(marker, method + marker, 1)
test.write_text(text, encoding='utf-8')
print('repaired memory opaque-id admission')
