// Fügt auf Detailseiten von SMW Central neben "Download" einen "Play"-Knopf ein.
// Er öffnet den SMW Play Launcher mit der Adresse der ZIP/BPS, die SMWC selbst verlinkt.
// Die Erweiterung lädt nichts und braucht keine Rechte außer der Seite selbst.
(function () {
	'use strict';

	// Nur Dateien vom Download-Host von SMWC, wie sie der Download-Knopf verlinkt.
	var DOWNLOAD_URL = /^https:\/\/dl\.smwcentral\.net\/(\d+)\/([^\/?#]+)$/;

	function slug(text) {
		return String(text || '')
			.toLowerCase()
			.replace(/[^a-z0-9]+/g, '-')
			.replace(/^-+|-+$/g, '')
			.slice(0, 60)
			.replace(/-+$/, '');
	}

	// smwplay://play?url=<Datei>&id=smwcentral:<name>-<SMWC-id>&title=<Titel>
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
