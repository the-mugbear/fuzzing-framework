declare module 'cytoscape-elk' {
  import type cytoscape from 'cytoscape';
  const register: (cy: typeof cytoscape) => void;
  export = register;
}
