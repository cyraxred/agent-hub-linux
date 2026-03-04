import React, { useState, useRef } from 'react';

export const WebPreviewView: React.FC = () => {
  const [url, setUrl] = useState('');
  const [loadedUrl, setLoadedUrl] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const handleNavigate = (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return;

    let targetUrl = url.trim();
    if (!targetUrl.startsWith('http://') && !targetUrl.startsWith('https://')) {
      targetUrl = `https://${targetUrl}`;
    }
    setLoadedUrl(targetUrl);
    setIsLoading(true);
  };

  const handleRefresh = () => {
    if (iframeRef.current && loadedUrl) {
      setIsLoading(true);
      iframeRef.current.src = loadedUrl;
    }
  };

  const handleOpenInBrowser = () => {
    if (loadedUrl) {
      window.open(loadedUrl, '_blank', 'noopener,noreferrer');
    }
  };

  return (
    <div className="web-preview-view">
      <div className="web-preview-toolbar">
        <button
          className="btn btn-ghost btn-sm"
          onClick={handleRefresh}
          disabled={!loadedUrl}
          title="Refresh"
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 2.5a5.487 5.487 0 00-4.131 1.869l1.204 1.204A.25.25 0 014.896 6H1.25A.25.25 0 011 5.75V2.104a.25.25 0 01.427-.177l1.38 1.38A7.001 7.001 0 0115 8a.75.75 0 01-1.5 0A5.5 5.5 0 008 2.5zM2.5 8a.75.75 0 00-1.5 0 7.001 7.001 0 0012.193 4.693l1.38 1.38a.25.25 0 00.427-.177V10.25a.25.25 0 00-.25-.25h-3.646a.25.25 0 00-.177.427l1.204 1.204A5.5 5.5 0 012.5 8z" />
          </svg>
        </button>
        <form className="web-preview-url-bar" onSubmit={handleNavigate}>
          <input
            type="text"
            className="web-preview-url-input"
            placeholder="Enter URL (e.g. localhost:3000)"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          <button type="submit" className="btn btn-primary btn-sm">
            Go
          </button>
        </form>
        <button
          className="btn btn-ghost btn-sm"
          onClick={handleOpenInBrowser}
          disabled={!loadedUrl}
          title="Open in browser"
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
            <path d="M3.75 2h3.5a.75.75 0 010 1.5h-3.5a.25.25 0 00-.25.25v8.5c0 .138.112.25.25.25h8.5a.25.25 0 00.25-.25v-3.5a.75.75 0 011.5 0v3.5A1.75 1.75 0 0112.25 14h-8.5A1.75 1.75 0 012 12.25v-8.5C2 2.784 2.784 2 3.75 2zm6.854-1h4.146a.25.25 0 01.25.25v4.146a.25.25 0 01-.427.177L13.03 4.03 9.28 7.78a.751.751 0 01-1.042-.018.751.751 0 01-.018-1.042l3.75-3.75-1.543-1.543A.25.25 0 0110.604 1z" />
          </svg>
        </button>
      </div>

      <div className="web-preview-content">
        {!loadedUrl ? (
          <div className="web-preview-empty">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1">
              <circle cx="12" cy="12" r="10" />
              <line x1="2" y1="12" x2="22" y2="12" />
              <path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" />
            </svg>
            <h3>Web Preview</h3>
            <p>Enter a URL above to preview a web application running locally or remotely.</p>
          </div>
        ) : (
          <>
            {isLoading && (
              <div className="web-preview-loading">
                <div className="spinner" />
                <p>Loading...</p>
              </div>
            )}
            <iframe
              ref={iframeRef}
              className="web-preview-iframe"
              src={loadedUrl}
              title="Web Preview"
              sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
              onLoad={() => setIsLoading(false)}
              onError={() => setIsLoading(false)}
              style={{ display: isLoading ? 'none' : 'block' }}
            />
          </>
        )}
      </div>
    </div>
  );
};
