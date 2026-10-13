"""Synthetic regression cases for the 13 October 2026 security audit."""
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dataeater_builder import packaging as p
from dataeater_builder.chunker import Chunk

class SecurityAuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.dir = Path(self.tmp.name)
        self.plain = self.dir/'plain.dataeater'; self.locked = self.dir/'locked.dataeater'
        build = p.DatabaseBuild('audit-db', 'Audit fixture')
        build.sources = [p.SourceRecord('s1', 'Synthetic')]
        build.chunks = [Chunk(text='The synthetic beacon is blue.', page_start=1, page_end=1, section='Test', source_id='s1', chunk_id='c1')]
        p.write_database(build, str(self.plain))
        self.creator, pub = p.create_creator_keypair(); self.public = p.make_request_code(pub)
        self.key, _ = p.encrypt_database_file(str(self.plain), str(self.locked), creator_public_key=self.public)
    def tearDown(self): self.tmp.cleanup()
    def changed_zip(self, name='changed.dataeater', transform=lambda manifest: None, extra=None):
        with zipfile.ZipFile(self.plain) as z: data = {n:z.read(n) for n in z.namelist()}
        manifest = json.loads(data['manifest.json']); transform(manifest); data['manifest.json'] = json.dumps(manifest).encode()
        path = self.dir/name
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
            for n,v in data.items(): z.writestr(n,v)
            if extra: z.writestr(*extra)
        return path
    def test_identifiers_must_be_exact_nonambiguous_strings(self):
        device = p.generate_device_keypair()
        for id in [None, '', ' ', ' db', 'db ', '.', '..', 'a/b', 'a\\b', 42, ['db'], 'a\x00b']:
            with self.subTest(id=id), self.assertRaises(ValueError): p.build_licence(self.key,device.public_key(),database_id=id)
        p.build_licence(self.key,device.public_key(),database_id='Audit-DB')
    def test_duplicate_and_suffix_bomb_are_rejected(self):
        duplicate=self.changed_zip(extra=('manifest.json',b'{}'))
        self.assertTrue(p.verify_database(str(duplicate)))
        bomb=self.changed_zip(extra=('unexpected',bytes(5000)))
        with patch.object(p,'MAX_ENTRY_BYTES',1024): self.assertTrue(p.verify_database(str(bomb)))
        with patch.object(p,'MAX_SCAN_BYTES',100): self.assertTrue(p.verify_database(str(self.plain)))
    def test_missing_hashes_and_malformed_manifest_rejected(self):
        for transform in [lambda m:m.update(files={}),lambda m:m.update(database_id=''),lambda m:m.update(database_id=42),lambda m:m.update(encryption='rot13'),lambda m:m.update(format_version=True)]:
            self.assertTrue(p.verify_database(str(self.changed_zip(transform=transform))))
    def test_encryption_does_not_launder_invalid_plaintext_hash(self):
        bad=self.changed_zip(transform=lambda m:m['files']['chunks.jsonl'].update(sha256='sha256:'+'0'*64))
        with self.assertRaises(ValueError):p.encrypt_database_file(str(bad),str(self.dir/'bad-locked'))
    def test_inspect_never_unbounded_reads_rejected_archive(self):
        bomb=self.changed_zip(extra=('unexpected',bytes(5000)))
        from dataeater_builder import cli
        args=type('Args',(),{'database':str(bomb)})()
        with patch.object(p,'MAX_ENTRY_BYTES',1024),patch.object(zipfile.ZipFile,'read',side_effect=AssertionError('unbounded read')):
            self.assertEqual(1,cli.command_inspect(args))
    def test_wrong_content_key_or_creator_cannot_issue_usable_code(self):
        from dataeater_builder import cli
        device=p.generate_device_keypair();secret=self.dir/'key.secret';creator=self.dir/'creator.key'
        p.write_secret_file(str(secret),bytes(32),'locked');p.write_creator_key_file(str(creator),self.creator,self.creator.public_key())
        args=type('Args',(),{'database':str(self.locked),'secret':str(secret),'key':str(creator),'request_code':p.make_request_code(device.public_key()),'expiry':'never','output':str(self.dir/'code.lic')})()
        self.assertEqual(1,cli.command_licence(args));self.assertFalse((self.dir/'code.lic').exists())
        other,_=p.create_creator_keypair();p.write_creator_key_file(str(creator),other,other.public_key());p.write_secret_file(str(secret),self.key,'locked')
        self.assertEqual(1,cli.command_licence(args))
    def test_fingerprint_changes_on_nonce_key_id_or_ciphertext(self):
        manifest,_=p.read_package(str(self.locked));original=p.database_fingerprint(manifest)
        for field,value in [('database_id','other'),('payload_nonce',base64.b64encode(bytes(12)).decode()),('creator_public_key',p.make_request_code(p.create_creator_keypair()[1]))]:
            modified=copy.deepcopy(manifest);modified[field]=value;self.assertNotEqual(original,p.database_fingerprint(modified))
        modified=copy.deepcopy(manifest);modified['files']['payload.enc']['sha256']='sha256:'+'1'*64;self.assertNotEqual(original,p.database_fingerprint(modified))
    def test_private_file_is_atomic_owner_only_without_symlink_follow(self):
        victim=self.dir/'victim';victim.write_text('keep');target=self.dir/'secret';target.symlink_to(victim)
        p.write_secret_file(str(target),self.key,'locked')
        self.assertEqual('keep',victim.read_text());self.assertFalse(target.is_symlink());self.assertEqual(0o600,target.stat().st_mode & 0o777)
        self.assertEqual(self.key,p.read_secret_file(str(target)))
    def test_nonce_and_wrap_validation(self):
        device=p.generate_device_keypair();wrap=p.wrap_content_key(self.key,device.public_key())
        self.assertEqual(self.key,p.unwrap_content_key(wrap,device))
        for field,value in [('nonce',base64.b64encode(bytes(8)).decode()),('wrapped_key',base64.b64encode(bytes(20)).decode())]:
            bad=copy.deepcopy(wrap);bad[field]=value
            with self.assertRaises(ValueError):p.unwrap_content_key(bad,device)
    def test_duplicate_and_deep_json_are_refused(self):
        for value in ['{"database_id":"a","database_\\u0069d":"b"}', "["*1000+"]"*1000]:
            with self.assertRaises(ValueError):p._json_loads(value)
    def test_android_incompatible_zip_compression_is_refused(self):
        path=self.dir/"unsupported.dataeater"
        with zipfile.ZipFile(path,"w",zipfile.ZIP_BZIP2) as z:z.writestr("manifest.json","{}")
        self.assertTrue(p.verify_database(str(path)))
    def test_archive_size_cap(self):
        with patch.object(p,'MAX_PACKAGE_BYTES',1):self.assertTrue(p.verify_database(str(self.plain)))

if __name__ == '__main__': unittest.main()
