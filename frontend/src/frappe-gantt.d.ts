declare module "frappe-gantt" {
  interface GanttTask {
    id: string;
    name: string;
    start: string;
    end: string;
    progress?: number;
    dependencies?: string;
    [key: string]: any;
  }

  interface GanttOptions {
    view_mode?: string;
    readonly?: boolean;
    popup_on?: string;
    popup?: (task: any) => string | false | void;
    on_click?: (task: GanttTask) => void;
    on_date_change?: (task: GanttTask, start: Date, end: Date) => void;
    custom_popup_html?: string | null;
    today_button?: boolean;
    view_mode_select?: boolean;
    scroll_to?: string | Date;
    [key: string]: any;
  }

  class Gantt {
    constructor(
      element: SVGElement | string,
      tasks: GanttTask[],
      options?: GanttOptions
    );
    tasks: GanttTask[];
    options: GanttOptions;
    $container: HTMLElement;
    $svg: SVGSVGElement;
    refresh(): void;
    change_view_mode(mode: string, maintain_pos?: boolean): void;
    update_options(new_options: Partial<GanttOptions>): void;
    scroll_current(): void;
  }

  export default Gantt;
}
