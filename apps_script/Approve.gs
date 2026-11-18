/**
 * One-click "Approve & post" / "Activate campaign" links for the clipping agent.
 *
 * The email link opens this page; nothing happens until you press the button
 * (so email link-scanners can't post anything by accident). The button asks
 * GitHub to run the "Approvals" workflow, which checks the secret code in the
 * link before posting/activating.
 *
 * SETUP (once):
 *  1. script.google.com -> New project -> paste this file -> Save.
 *  2. Project Settings (gear) -> Script properties -> add:
 *       GITHUB_TOKEN = a fine-grained GitHub token (only this repo,
 *                      permission "Contents: Read and write")
 *       REPO         = wasimwu01-a11y/Kidify-daily-video-pipeline
 *  3. Deploy -> New deployment -> type "Web app" ->
 *       Execute as: Me   |   Who has access: Anyone  -> Deploy -> authorise.
 *  4. Copy the Web app URL (ends in /exec) and save it in GitHub:
 *       repo Settings -> Secrets and variables -> Actions -> Variables ->
 *       New repository variable: APPROVE_URL = that URL
 */

function doGet(e) {
  var p = e.parameter || {};
  var action = p.action, id = p.id, t = p.t;
  if (['publish', 'activate'].indexOf(action) === -1 || !id || !t) {
    return page('<p>This link is incomplete. Use the GitHub option in the email instead.</p>');
  }
  var label = action === 'publish' ? 'Approve &amp; post now' : 'Activate this campaign';
  var note = action === 'publish'
    ? 'It goes live on YouTube in about 2 minutes. Be ready to submit the link in Content Rewards within 30 minutes.'
    : 'The agent will start making videos for this campaign from the next daily run.';
  return page(
    '<p>' + note + '</p>' +
    '<button id="go" onclick="go()">' + label + '</button>' +
    '<p id="msg"></p>' +
    '<script>' +
    'function go(){var b=document.getElementById("go");b.disabled=true;b.textContent="Sending...";' +
    'google.script.run.withSuccessHandler(function(m){document.getElementById("msg").innerHTML=m;b.style.display="none";})' +
    '.withFailureHandler(function(err){document.getElementById("msg").textContent="Error: "+err;b.disabled=false;})' +
    '.dispatch(' + JSON.stringify(action) + ',' + JSON.stringify(id) + ',' + JSON.stringify(t) + ');}' +
    '</script>');
}

function dispatch(action, id, t) {
  var props = PropertiesService.getScriptProperties();
  var res = UrlFetchApp.fetch('https://api.github.com/repos/' + props.getProperty('REPO') + '/dispatches', {
    method: 'post',
    contentType: 'application/json',
    muteHttpExceptions: true,
    headers: {
      Authorization: 'Bearer ' + props.getProperty('GITHUB_TOKEN'),
      Accept: 'application/vnd.github+json'
    },
    payload: JSON.stringify({
      event_type: action === 'publish' ? 'publish-clip' : 'activate-campaign',
      client_payload: { id: id, t: t }
    })
  });
  if (res.getResponseCode() === 204) {
    return action === 'publish'
      ? '&#9989; Approved. Watch your inbox for the <b>LIVE NOW</b> email (about 2 minutes), then submit the link.'
      : '&#9989; Done. You will get a confirmation email shortly.';
  }
  return '&#10060; GitHub said ' + res.getResponseCode() + '. Check the GITHUB_TOKEN script property, or use the GitHub option in the email.';
}

function page(body) {
  return HtmlService.createHtmlOutput(
    '<div style="font-family:Arial,sans-serif;font-size:18px;max-width:520px;margin:24px auto;padding:0 16px">' +
    '<h2>Clipping agent</h2>' + body +
    '<style>button{font-size:20px;padding:14px 22px;border:0;border-radius:10px;background:#16a34a;color:#fff}</style>' +
    '</div>').setTitle('Clipping agent').addMetaTag('viewport', 'width=device-width, initial-scale=1');
}
