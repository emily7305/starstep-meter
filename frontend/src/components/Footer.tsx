const REPO_URL = "https://github.com/emily7305/starstep-meter";

export function Footer() {
  return (
    <footer className="footer">
      <span>made by Emily</span>
      <a className="footer__link mono" href={REPO_URL} target="_blank" rel="noreferrer" title="the source on github">
        github.com/emily7305/starstep-meter
      </a>
      <span>source available, free for noncommercial use (PolyForm Noncommercial 1.0.0)</span>
    </footer>
  );
}
