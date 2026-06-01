import React, { useEffect, useState, useRef } from 'react';
import Editor from '@monaco-editor/react';
import { api } from '../api/client';

export default function SourceViewer({ nodeId, language, onGoToDefinition }) {
  const [source, setSource] = useState('');
  const [loading, setLoading] = useState(true);
  const providerRef = useRef(null);
  const onGoToDefinitionRef = useRef(onGoToDefinition);

  useEffect(() => {
    onGoToDefinitionRef.current = onGoToDefinition;
  }, [onGoToDefinition]);

  useEffect(() => {
    if (!nodeId) return;
    setLoading(true);
    api.nodeSource(nodeId)
      .then(data => {
        setSource(data.source || '');
        setLoading(false);
      })
      .catch(err => {
        setSource('// Error loading source\n' + err.message);
        setLoading(false);
      });
  }, [nodeId]);

  useEffect(() => {
    // Cleanup provider on unmount
    return () => {
      if (providerRef.current) {
        providerRef.current.dispose();
      }
    };
  }, []);

  const mapLanguage = (lang) => {
    const l = lang?.toLowerCase();
    if (l === 'python') return 'python';
    if (l === 'javascript' || l === 'js') return 'javascript';
    if (l === 'typescript' || l === 'ts') return 'typescript';
    if (l === 'tsx') return 'typescript';
    if (l === 'go') return 'go';
    if (l === 'java') return 'java';
    if (l === 'rust') return 'rust';
    if (l === 'c') return 'c';
    if (l === 'cpp' || l === 'c++') return 'cpp';
    if (l === 'c_sharp' || l === 'c#') return 'csharp';
    if (l === 'php') return 'php';
    if (l === 'zig') return 'zig';
    if (l === 'ruby') return 'ruby';
    if (l === 'swift') return 'swift';
    if (l === 'kotlin') return 'kotlin';
    if (l === 'scala') return 'scala';
    if (l === 'lua') return 'lua';
    if (l === 'bash' || l === 'sh') return 'shell';
    if (l === 'sql') return 'sql';
    return 'plaintext';
  };

  const handleEditorDidMount = (editor, monaco) => {
    // Implement Go to Definition
    if (providerRef.current) {
      providerRef.current.dispose();
    }

    const langId = mapLanguage(language);
    if (!langId || langId === 'plaintext') return;

    providerRef.current = monaco.languages.registerDefinitionProvider(langId, {
      provideDefinition: async (model, position) => {
        const word = model.getWordAtPosition(position);
        if (!word) return null;

        const identifier = word.word;
        // Short-circuit for trivial identifiers
        if (!identifier || identifier.length < 2 || /^\d+$/.test(identifier)) {
          return null;
        }

        // Short-circuit for very large files
        if (model.getLineCount() > 5000) {
          return null;
        }

        try {
          // Search for the symbol in the workspace
          const results = await api.search(identifier, { fuzzy: false });
          if (results.results && results.results.length > 0) {
            const top = results.results[0];
            // Invoke callback via ref to avoid stale closure
            if (onGoToDefinitionRef.current) {
              onGoToDefinitionRef.current(top.id);
            }
          }
        } catch (e) {
          console.error('Search failed', e);
        }
        return null;
      }
    });
  };

  if (loading) {
    return (
      <div className="source-viewer loading" style={{ height: '400px', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#0d1117', color: '#8b949e', border: '1px solid #30363d', borderRadius: '6px' }}>
        <span>Loading source…</span>
      </div>
    );
  }

  return (
    <div className="source-viewer" style={{ height: '400px', border: '1px solid #30363d', borderRadius: '6px', overflow: 'hidden' }}>
      <Editor
        height="100%"
        language={mapLanguage(language)}
        theme="vs-dark"
        value={source}
        options={{
          readOnly: true,
          minimap: { enabled: false },
          fontSize: 12,
          scrollBeyondLastLine: false,
          automaticLayout: true,
          domReadOnly: true,
        }}
        onMount={handleEditorDidMount}
      />
    </div>
  );
}
