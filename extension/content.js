// Adds a "Play" button next to "Download" on SMW Central detail pages.
// It opens the SMW Play Launcher with the address of the ZIP/BPS that SMWC itself links.
// The extension downloads nothing and needs no permissions beyond the page itself.
(function () {
	'use strict';

	// Only files from SMWC's download host, as linked by the Download button.
	var DOWNLOAD_URL = /^https:\/\/dl\.smwcentral\.net\/(\d+)\/([^\/?#]+)$/;

	function slug(text) {
		return String(text || '')
			.toLowerCase()
			.replace(/[^a-z0-9]+/g, '-')
			.replace(/^-+|-+$/g, '')
			.slice(0, 60)
			.replace(/-+$/, '');
	}

	// smwplay://play?url=<file>&id=smwcentral:<name>-<SMWC-id>&title=<title>
	function buildLink(href, title) {
		var m = DOWNLOAD_URL.exec(href || '');
		if (!m) return null;
		var name = slug(title) || slug(m[2].replace(/\.[a-z0-9]+$/i, '')) || 'hack';
		var q = new URLSearchParams({
			url: href,
			id: 'smwcentral:' + name + '-' + m[1],
			title: String(title || '').trim().slice(0, 100)
		});
		if (!q.get('title')) q.delete('title');
		return 'smwplay://play?' + q.toString().replace(/\+/g, '%20');
	}

	function addPlayButton(doc) {
		if (doc.getElementById('smwplay-button')) return false;
		var download = doc.querySelector('#file-download-button');
		if (!download) return false;
		var titleEl = doc.querySelector('#submission-header .title');
		var link = buildLink(download.getAttribute('href'), titleEl ? titleEl.textContent : '');
		if (!link) return false;
		var a = doc.createElement('a');
		a.id = 'smwplay-button';
		a.className = 'button action';
		a.href = link;
		a.title = 'Download, patch and start with the SMW Play Launcher';
		a.textContent = 'Play';
		download.parentNode.insertBefore(a, download);
		return true;
	}

	if (typeof module !== 'undefined' && module.exports) {
		module.exports = { slug: slug, buildLink: buildLink, addPlayButton: addPlayButton };
	} else {
		addPlayButton(document);
	}
})();
