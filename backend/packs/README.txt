Drop definition packs (.jar or .zip) here. They are picked up automatically (no restart needed).
Inside the jar, mirror backend/app/definitions/ :
  workflows/<flow-id>/flow.yaml | ui.yaml | templates/*.xml
  templates/*.xml, flows/*.yaml, ui/*.yaml
Packs override core files with the same id/path; later jar names (alphabetical) override earlier ones.
Only .yaml/.yml/.xml are read. api-catalog.yaml and schemas/ in a jar are ignored on purpose.
Check what is loaded:  GET /api/packs
