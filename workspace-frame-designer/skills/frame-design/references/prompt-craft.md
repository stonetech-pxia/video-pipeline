# Prompt Craft

What a video prompt says when the reference images already carry the faces and the room.

## The division of labour

A generation gets two inputs: this prompt, and the reference images bound to the segment. They are not two chances to say the same thing. They answer different questions.

- **The reference images answer "what does it look like."** Who this person is, the shape of their face, the colour of the walls, the light in that room. That is settled before the prompt is written, and the prompt cannot improve on it.
- **The prompt answers "what happens."** Action, camera movement, visible emotion, sound, and the order they arrive in.

So: **name the subject, do not describe it.** Write 周砚 and 分拣室. Do not write his height, his face, the institutional green of the walls, the brass scale on the counter.

This is not a style preference. A prompt that describes an appearance the reference already fixes hands the model two sources for one fact, and the two never match exactly. The model reconciles them, and what it produces is neither.

## Where the environment detail went

The director settled the light direction, the surfaces, the depth, the background life. `resolve_assets.py` appended that text to the location's `settled` list in the asset registry, where it becomes the basis of the location reference image.

It is already accounted for. Restating it in the video prompt is the same double-source problem in a different coat.

Raise an ambiguity only when the shot left something unsaid that the action genuinely depends on.

## The three sections

`integrated_multimodal_description`
: What happens, in order, across the shots the segment covers. A segment can span a cut — the shot changes inside one generation — so say so plainly and keep the order the `shot_bindings` give. Camera behaviour belongs here: what moves, how slowly, toward what. So does visible emotion, as something a viewer could see rather than a state you assert.

`overall_soundscape`
: Diegetic sound only — what exists in the world of the shot. Take it from each shot's `diegetic_audio`. Room tone, the sound of the action, what carries in from outside.

`non_diegetic_music`
: Score, from Shot IR's `music`. Empty string when there is none, which is most of the time. Do not invent a mood cue because the field exists.

## Dialogue and visible text

Copy them exactly as the shot writes them. Not paraphrased, not translated, not re-punctuated. They were locked upstream and a change here is a change to the film.

## Carrying state into a cold start

A segment that opens a scene has no previous frame; the location changed, so the last generation's final frame shows somewhere else entirely. Everything that survived the change has to arrive in words.

Not everything survives. `staging`, `scene_state`, and `lighting_state` belong to the place that was left behind, and reset with it. **`wardrobe_state` and `held_props` do not** — the coat is still buttoned, the photograph is still in the pocket — and they must appear word for word, because a deterministic checker looks for exactly that text.

Word for word is a floor, not a ceiling. Place the phrase where it reads as part of the action rather than dropped in front of it; a restatement that turns the sentence into a list has satisfied the checker and failed the shot.
