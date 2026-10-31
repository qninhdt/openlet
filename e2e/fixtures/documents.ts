import { strToU8, zipSync } from 'fflate';

export function recoveryGuide() {
  return Buffer.from(zipSync({
    '[Content_Types].xml': strToU8('<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'),
    '_rels/.rels': strToU8('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="document" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'),
    'word/document.xml': strToU8('<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Storage recovery guide</w:t></w:r></w:p><w:p><w:r><w:t>Recovery requires durable metadata and matching object bytes. Stop all writers before taking a coordinated recovery point. Verify the restored bytes before resuming publication.</w:t></w:r></w:p><w:p><w:r><w:t>Lunar basalt samples use the independently searchable identifier ORBITAL-RECOVERY-7421.</w:t></w:r></w:p><w:sectPr/></w:body></w:document>'),
  }));
}
