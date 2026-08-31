SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((((((movie_companies CROSS JOIN (title CROSS JOIN complete_cast)) CROSS JOIN movie_link) CROSS JOIN aka_title) CROSS JOIN link_type) CROSS JOIN keyword) CROSS JOIN company_name) CROSS JOIN cast_info) CROSS JOIN role_type) CROSS JOIN movie_info) CROSS JOIN movie_keyword
WHERE aka_title.season_nr = 1
  AND company_name.name_pcode_sf = 'B3513'
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.role_id = role_type.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id;
