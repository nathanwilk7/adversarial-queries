SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((title CROSS JOIN aka_title) CROSS JOIN complete_cast) CROSS JOIN movie_companies) CROSS JOIN movie_info) CROSS JOIN movie_keyword) CROSS JOIN movie_link
WHERE aka_title.season_nr = 1
  AND aka_title.movie_id = title.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id;
