'use client'

import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Lightbulb, Sparkles, Plus, Trash2 } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'
import { SourceInsightResponse } from '@/lib/api/insights'
import { Transformation } from '@/lib/types/transformations'

interface SourceInsightsTabProps {
  insights: SourceInsightResponse[]
  loadingInsights: boolean
  transformations: Transformation[]
  selectedTransformation: string
  onSelectTransformation: (value: string) => void
  creatingInsight: boolean
  onCreateInsight: () => void
  onViewInsight: (insight: SourceInsightResponse) => void
  onDeleteInsight: (insightId: string) => void
}

export function SourceInsightsTab({
  insights,
  loadingInsights,
  transformations,
  selectedTransformation,
  onSelectTransformation,
  creatingInsight,
  onCreateInsight,
  onViewInsight,
  onDeleteInsight,
}: SourceInsightsTabProps) {
  const { t } = useTranslation()

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span className="flex items-center gap-2">
            <Lightbulb className="h-5 w-5" />
            {t('common.insights')}
          </span>
          <Badge variant="secondary">{insights.length}</Badge>
        </CardTitle>
        <CardDescription>
          {t('sources.insightsDesc')}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Create New Insight */}
        <div className="rounded-lg border bg-muted/30 p-4">
          <Label
            htmlFor="transformation-select"
            className="mb-3 text-sm font-semibold flex items-center gap-2"
          >
            <Sparkles className="h-4 w-4" />
            {t('sources.generateNewInsight')}
          </Label>
          <div className="flex gap-2">
            <Select
              name="transformation"
              value={selectedTransformation}
              onValueChange={onSelectTransformation}
              disabled={creatingInsight}
            >
              <SelectTrigger id="transformation-select" className="flex-1">
                <SelectValue placeholder={t('sources.selectTransformation')} />
              </SelectTrigger>
              <SelectContent>
                {transformations.map((trans) => (
                  <SelectItem key={trans.id} value={trans.id}>
                    {trans.title || trans.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              size="sm"
              onClick={onCreateInsight}
              disabled={!selectedTransformation || creatingInsight}
            >
              {creatingInsight ? (
                <>
                  <LoadingSpinner className="mr-2 h-3 w-3" />
                  {t('common.creating')}
                </>
              ) : (
                <>
                  <Plus className="mr-2 h-4 w-4" />
                  {t('common.create')}
                </>
              )}
            </Button>
          </div>
        </div>

        {/* Insights List */}
        {loadingInsights ? (
          <div className="flex items-center justify-center py-8">
            <LoadingSpinner />
          </div>
        ) : insights.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            <Lightbulb className="h-12 w-12 mx-auto mb-3 opacity-50" />
            <p className="text-sm">{t('sources.noInsightsYet')}</p>
            <p className="text-xs mt-1">{t('sources.createFirstInsight')}</p>
          </div>
        ) : (
          <div className="space-y-3">
            {insights.map((insight) => (
              <div key={insight.id} className="rounded-lg border bg-background p-4">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-xs uppercase">
                      {insight.insight_type}
                    </Badge>
                  </div>
                </div>
                <p className="mt-2 text-sm text-muted-foreground">
                  {insight.content.slice(0, 180)}{insight.content.length > 180 ? '…' : ''}
                </p>
                <div className="mt-3 flex justify-end gap-2">
                  <Button size="sm" variant="outline" onClick={() => onViewInsight(insight)}>
                    {t('sources.viewInsight')}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => onDeleteInsight(insight.id)}
                    className="text-destructive hover:text-destructive"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
