// node --test launcher/extension
const test = require('node:test');
const assert = require('node:assert');
const { slug, buildLink, addPlayButton } = require('./content.js');

// Ausschnitt einer echten Detailseite (id=39701)
const PAGE = `<div id="submission-header">
<div class="title-section"><h4 class="title">Saphros Blindrace #2</h4></div>
<div class="button-section"><div class="button-group">
<a id="file-preview-button" class="button action" href="#">Patch Now</a>
<a id="file-download-button" class="button suggested" href="https://dl.smwcentral.net/39701/Saphros_Blindrace_2.zip">Download</a>
</div></div></div>`;

// Minimal stand-in for document that reads the fixture
function fakeDoc(html) {
	const inserted = [];
	const href = /id="file-download-button"[^>]*href="([^"]*)"/.exec(html);
	const title = /<h4 class="title">([^<]*)<\/h4>/.exec(html);
	const parent = { insertBefore: (el, ref) => inserted.push({ el, ref }) };
	const download = href && { getAttribute: () => href[1], parentNode: parent };
	return {
		inserted,
		getElementById: (id) => (id === 'smwplay-button' ? inserted[0]?.el ?? null : null),
		querySelector: (sel) =>
			sel === '#file-download-button' ? download : sel === '#submission-header .title' ? title && { textContent: title[1] } : null,
		createElement: () => ({})
	};
}

test('slug', () => {
	assert.strictEqual(slug('Saphros Blindrace #2'), 'saphros-blindrace-2');
	assert.strictEqual(slug('  ***  '), '');
	assert.ok(slug('x'.repeat(200)).length <= 60);
});

test('link for the real page', () => {
	const link = buildLink('https://dl.smwcentral.net/39701/Saphros_Blindrace_2.zip', 'Saphros Blindrace #2');
	const u = new URL(link);
	assert.strictEqual(u.protocol, 'smwplay:');
	assert.strictEqual(u.searchParams.get('url'), 'https://dl.smwcentral.net/39701/Saphros_Blindrace_2.zip');
	assert.strictEqual(u.searchParams.get('id'), 'smwcentral:saphros-blindrace-2-39701');
	assert.strictEqual(u.searchParams.get('title'), 'Saphros Blindrace #2');
	assert.ok(!link.includes('+'));
});

test('without a title the name comes from the file', () => {
	const u = new URL(buildLink('https://dl.smwcentral.net/5/My_Hack.zip', ''));
	assert.strictEqual(u.searchParams.get('id'), 'smwcentral:my-hack-5');
	assert.strictEqual(u.searchParams.get('title'), null);
});

test('only files from dl.smwcentral.net', () => {
	for (const bad of [
		'http://dl.smwcentral.net/1/a.zip',
		'https://evil.example/1/a.zip',
		'https://dl.smwcentral.net.evil.example/1/a.zip',
		'https://dl.smwcentral.net/x/a.zip',
		'javascript:alert(1)',
		'#',
		'',
		null
	]) {
		assert.strictEqual(buildLink(bad, 'T'), null, String(bad));
	}
});

test('places the button before "Download", only once', () => {
	const doc = fakeDoc(PAGE);
	assert.strictEqual(addPlayButton(doc), true);
	const { el } = doc.inserted[0];
	assert.strictEqual(el.id, 'smwplay-button');
	assert.strictEqual(el.textContent, 'Play');
	assert.ok(el.href.startsWith('smwplay://play?url='));
	assert.strictEqual(addPlayButton(doc), false);
	assert.strictEqual(doc.inserted.length, 1);
});

test('pages without a download button stay untouched', () => {
	const doc = fakeDoc('<div>nichts</div>');
	assert.strictEqual(addPlayButton(doc), false);
	assert.strictEqual(doc.inserted.length, 0);
});
