import React, { useEffect, useState, useRef } from 'react';
import Editor from '@monaco-editor/react';
import { api } from '../api/client';

export default function SourceViewer({ nodeId, language, onGoToDefinition }) {
  const [source, setSource] = useState('Loading source...');
  const [loading, setLoading] = useState(true);
  const providerRef = useRef(null);

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

  const handleEditorDidMount = (editor, monaco) => {
    // Implement Go to Definition
    // Cleanup existing provider if any
    if (providerRef.current) {
      providerRef.current.dispose();
    }

    providerRef.current = monaco.languages.registerDefinitionProvider('*', {
      provideDefinition: async (model, position) => {
        const word = model.getWordAtPosition(position);
        if (!word) return null;

        try {
          // Search for the symbol in the workspace
          const results = await api.search(word.word, { fuzzy: false });
          if (results.results && results.results.length > 0) {
            const top = results.results[0];
            // We return a location that Monaco can use
            // For now, we'll just trigger the onGoToDefinition callback
            // since we want to navigate the whole UI to that node
            onGoToDefinition(top.id);
          }
        } catch (e) {
          console.error('Search failed', e);
        }
        return null;
      }
    });
  };

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
