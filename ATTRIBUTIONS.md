# Attributions

## Hermes Agent

Hermes Pet monitors [Hermes Agent](https://github.com/NousResearch/hermes-agent), an open-source AI agent framework. The live-state session contract was designed for upstream contribution. Hermes is used under the terms of its license.

## Inspiration

The pet companion concept was inspired by [Codex Pet Share](https://codex-pets.net/), a community gallery of desktop companions for AI coding agents. Hermes Pet is an independent implementation — it is not affiliated with or endorsed by Codex Pet Share or OpenAI.

## Pet Assets

### border-collie-v2 (default pet)

The border-collie-v2 sprite set was sourced from the Codex Pet Share community. These assets are **included for compatibility and demo purposes** and are **not** covered by the MIT license:

- Source: https://codex-pets.net/#/pets/border-collie
- Attribution: Community-shared Codex Pet
- License: Community shared (see `assets/pets/border-collie-v2/LICENSE-NOTE.md`)

The codebase (Python, C#, scripts) is MIT-licensed. Third-party pet assets in `assets/pets/` may have separate terms; see their respective `LICENSE-NOTE.md`.

**If you are redistributing this project:** Consider replacing the border-collie-v2 sprites with your own artwork.

### Creating your own pet

See `src/wpf/HermesPet/PetAssetManager.cs` for the pet manifest schema. Place sprite sheets in `assets/pets/<name>/` and create a `pet.json` manifest with frame rectangles and state mappings.

---

*If you believe any asset or dependency requires additional attribution, please open an issue.*
