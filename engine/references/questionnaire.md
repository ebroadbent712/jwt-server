# Just Wear This client questionnaire

Clients answer six questions (about three minutes on a phone). The easiest way is the photographer's questionnaire page (`scripts/build_questionnaire.py`): one public link she sends every client, which ends with Text / Email / Copy my answers. Its message opens with a one-line greeting (ignore it), then "Just Wear This outfit questions" and the numbered answers below. The same questions can also be pasted into any form. The photographer adds the session details she already knows. Answers can arrive in any format: pasted from Google Forms, a client system like HoneyBook or Dubsado, an email or a text. Read them as written; never require a specific format.

## Photographer adds (from the booking)

- Session type (family, extended family, couple, maternity)
- Date (month is enough)
- Location and setting
- Time of day
- Indoor or outdoor
- Optional: anything for this family's "Before your session" section (add a vendor, or skip one)

If any of the first five are missing, ask the photographer in one short message. Never ask the client.

## Intro the client sees

> Let's take outfits off your to-do list! Answer a few quick questions and I'll send you a personal outfit page for your family: tap any piece to shop it at a few price points, and check things off as they arrive. About three minutes.

## Client questions

**1. Tell me about everyone in the photos.** For each person:
- First name, or Mom / Dad / Grandma
- Age group: Adult · Teen · Kid (with age) · Toddler · Baby
- Shop from: Women's · Men's · Girls' · Boys' · Either (babies too)
- Dressing up: Happy to · Basics only (jeans and a nice top)
- Anything they won't wear? (optional) For example: heels, patterns, ties, collars, bows, scratchy fabrics

**2. How dressy would you like to be?** Relaxed · Dressy casual · Polished · Formal · Not sure, you decide

**3. Any colors you love, or never want to see?** We'll keep them out of prints too. (optional)

**4. How do you feel about prints?** Love them · A little is nice · Solids please

**5. Anything you already own and want to wear, shoes included?** Add a photo and who it's for. If the photos will hang in your home, you can add a photo of the room too. (optional)

**6. Anything else I should know?** Comfort needs, pregnancy, mobility or sensory needs, modesty, or anything you're nervous about. (optional)

## Closing message

> Thank you! Your outfit page will be on its way soon. Watch for a link from me.

## How answers map to the plan

| Answer | Use |
| --- | --- |
| Names, ages, shop from | Board labels, layout order (adults first, then kids oldest to youngest), which library pieces fit. Use the names exactly as given; the client page is a shareable link, so first names only |
| Baby shop from | Girls' → dresses and a bow headband; Boys' → sets; Either → neutral pieces (`baby_for` tag) |
| "Basics only" | The won't-dress-up rule |
| Won't wear | Hard no's (highest priority). "Bows" means no headband for a baby girl |
| Dress level | `dress_level` in the plan, shown on the board; "Not sure" → choose from the setting (usually Dressy casual) |
| Colors | Color story choice; a never color is ruled out everywhere, including lines in prints |
| Prints | "Solids please" → no prints, texture carries interest; "Love them" → pattern mixing allowed within the rules |
| Owned pieces (and shoes) | `owned` list; build around them. They show as "You have this" on the board and start as "Have it" on the client page |
| Room photo | Weigh the room's colors when choosing the story |
| Anything else | Sensitive-case rules |
| Photographer's vendor note | `recommendations` or `skip_recommendations` in the plan |

No sizes and no budget: clients choose sizes and price tiers on the shop links. No household grouping for extended families; if the photographer mentions households, group those people next to each other on the board.

## Gift path (no questionnaire)

A photographer can surprise a client with a plan before sending any questions: "Make a board for the Lees: Sarah, Mike, Ava 6, baby boy Theo, Loose Park in October." Build it from what she gives (people, ages, setting, season) with these defaults, and say them in one line when you deliver:

- Dress level: Dressy casual
- Prints: A little is nice
- Colors: the color story that best suits the setting, season and her editing style
- No owned pieces

If only roles are given ("mom, dad, two boys"), use those as labels. If a baby's girl or boy isn't clear, use neutral pieces. After delivering, offer once: "Want me to adjust anything once they've seen it?" so the client's reactions can tune the board.
