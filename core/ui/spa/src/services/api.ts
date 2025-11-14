/**
 * API configuration and utilities
 */

export const API_BASE = import.meta.env.VITE_API_BASE ?? '';

/**
 * Generic API fetch wrapper with automatic error handling
 */
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
    ...init,
  });
  if (!response.ok) {
    let errorMessage = response.statusText;
    try {
      const errorData = await response.json();
      errorMessage = errorData.detail || errorData.message || response.statusText;
    } catch (parseError) {
      // If JSON parsing fails, use the statusText
      errorMessage = response.statusText;
    }
    throw new Error(errorMessage);
  }
  if (response.status === 204) {
    return {} as T;
  }
  return response.json();
}
