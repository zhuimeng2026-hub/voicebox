import { useMutation } from '@tanstack/react-query';
import { apiClient } from '@/lib/api/client';
import type { SampleQualityResult } from '@/lib/api/types';

interface AnalyzeParams {
  profileId: string;
  audioBlob: Blob;
  referenceText: string;
}

export function useSampleQuality() {
  return useMutation<SampleQualityResult, Error, AnalyzeParams>({
    mutationFn: async ({ profileId, audioBlob, referenceText }) => {
      const formData = new FormData();
      formData.append('file', audioBlob, 'recording.webm');
      formData.append('reference_text', referenceText);
      return apiClient.analyzeSampleQuality(profileId, formData);
    },
  });
}
