const API_BASE_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000') + '/api';

// Helper function to ensure URL has correct format
const getApiUrl = (path) => {
  const baseUrl = API_BASE_URL.endsWith('/') ? API_BASE_URL.slice(0, -1) : API_BASE_URL;
  const cleanPath = path.startsWith('/') ? path : `/${path}`;
  return `${baseUrl}${cleanPath}`;
};

class ApiService {
  async get(path, options = {}) {
    const response = await fetch(getApiUrl(path), {
      ...options,
      headers: {
        'Accept': 'application/json',
        ...(options.headers || {})
      }
    });
    
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `Failed to fetch: ${response.status}`);
    }
    
    return response.json();
  }

  async post(path, data = null, options = {}) {
    const response = await fetch(getApiUrl(path), {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        ...(options.headers || {})
      },
      body: data ? JSON.stringify(data) : undefined,
      ...options
    });
    
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `Failed to post: ${response.status}`);
    }
    
    return response.json();
  }

  async delete(path, options = {}) {
    const response = await fetch(getApiUrl(path), {
      method: 'DELETE',
      headers: {
        'Accept': 'application/json',
        ...(options.headers || {})
      },
      ...options
    });
    
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `Failed to delete: ${response.status}`);
    }
    
    return response.json();
  }

  async put(path, data = null, options = {}) {
    const response = await fetch(getApiUrl(path), {
      method: 'PUT',
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        ...(options.headers || {})
      },
      body: data ? JSON.stringify(data) : undefined,
      ...options
    });
    
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `Failed to put: ${response.status}`);
    }
    
    return response.json();
  }
}

export const apiService = new ApiService();
